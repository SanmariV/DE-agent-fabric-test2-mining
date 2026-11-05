"""Render the Power BI semantic model (TMDL) from the gold specs.

The semantic model is the Fabric counterpart of a Databricks metric view:
one governed definition of the measures and the dimensions you can slice
them by. Copilot and Fabric Data Agents answer questions from it, so every
description, synonym and AI instruction in the specs ends up in the model.

TMDL has no comment syntax for a "do not edit" notice, so ``python -m fde
check`` (rule R1) is what catches a hand edit.

Rendered output (Fabric Git format, a ``.SemanticModel`` item)::

    fabric/<sm>.SemanticModel/.platform
    fabric/<sm>.SemanticModel/definition.pbism
    fabric/<sm>.SemanticModel/definition/database.tmdl
    fabric/<sm>.SemanticModel/definition/model.tmdl
    fabric/<sm>.SemanticModel/definition/expressions.tmdl
    fabric/<sm>.SemanticModel/definition/relationships.tmdl  (if any)
    fabric/<sm>.SemanticModel/definition/tables/<Table>.tmdl

The model is **Direct Lake on the Warehouse SQL endpoint**: no data is
copied, and every table reads ``wh_gold`` directly.

What comes from where:

| Model object | Spec |
| --- | --- |
| table, column | gold table and its columns (+ the kit's ``_SK`` and SCD2 columns) |
| relationship | a column's ``references:`` (many to one, fact -> dimension) |
| measure | the fact's ``measures:`` (``expression`` translated to DAX, or ``dax:``) |
| description | the spec description, then ``Also known as:`` synonyms |
| AI guidance | the table's ``ai_instructions:`` |

Personal data: with ``ai.pii: exclude`` in ``fde.yml`` (the default) a column
marked ``meta.pii: true`` is left out of the model, so no AI item can read it.

[Spike] Synonyms are written into descriptions. Confirm whether to move them
to the culture's linguistic metadata once that format is stable for Direct
Lake models.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from fde.project import Model, Project

TAB = "\t"
SQL_ENDPOINT_PLACEHOLDER = "SQL_ENDPOINT_PLACEHOLDER"
WAREHOUSE_PLACEHOLDER = "00000000-0000-0000-0000-0000000000a2"
SEMANTIC_MODEL_PLACEHOLDER = "00000000-0000-0000-0000-0000000000a3"

MEASURE_PATTERN = re.compile(
    r"^\s*(?P<func>sum|avg|min|max|count)\s*\(\s*(?P<distinct>distinct\s+)?"
    r"(?P<column>[A-Za-z_]\w*|\*)\s*\)\s*$", re.I)
DAX_FUNCTIONS = {"sum": "SUM", "avg": "AVERAGE", "min": "MIN", "max": "MAX",
                 "count": "COUNT"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ModelColumn:
    """One column of a semantic model table.

    Attributes:
        name: Column name.
        data_type: Warehouse type.
        description: Business description (with synonyms).
        hidden: True for keys that only exist to join tables.
        pii: True when the column holds personal data.
        synonyms: Other names for the column.
    """

    name: str
    data_type: str
    description: str
    hidden: bool
    pii: bool
    synonyms: List[str]


def synonym_list(value) -> List[str]:
    """Return synonyms as a clean list of strings.

    Args:
        value: The ``synonyms:`` value from a spec.

    Returns:
        The non-empty entries, or an empty list when the value is not a list.
    """
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def with_synonyms(description: str, synonyms) -> str:
    """Append ``Also known as: ...`` to a description.

    Args:
        description: The spec description.
        synonyms: The ``synonyms:`` value.

    Returns:
        One line of text.
    """
    text = " ".join(str(description or "").split())
    names = synonym_list(synonyms)
    if names:
        text = f"{text} Also known as: {', '.join(names)}.".strip()
    return text


def model_columns(project: Project, model: Model) -> List[ModelColumn]:
    """Return the columns of a gold table as the semantic model shows them.

    Args:
        project: The loaded project.
        model: A gold model.

    Returns:
        Surrogate key (hidden), declared columns and SCD2 columns. PII
        columns are left out when ``ai.pii`` is ``exclude``.
    """
    out = [ModelColumn(model.surrogate_key, "bigint",
                       f"Surrogate key of {model.name}.", True, False, [])]
    for col in model.columns:
        if col.pii and project.config.ai_pii == "exclude":
            continue
        out.append(ModelColumn(
            col.name, col.data_type,
            with_synonyms(col.description or "", col.synonyms),
            col.name.endswith("_SK"), col.pii, synonym_list(col.synonyms)))
    if model.is_scd2:
        out += [
            ModelColumn("StartDate", "date",
                        "First date this version is valid.", False, False, []),
            ModelColumn("EndDate", "date", "Last date this version is valid "
                        "(9999-12-31 for the current version).", False,
                        False, []),
            ModelColumn("IsCurrent", "bit", "1 for the current version.",
                        False, False, []),
        ]
    return out


def measure_dax(model: Model, measure: dict) -> Optional[str]:
    """Translate a measure to DAX.

    A measure may give ``dax:`` itself. Otherwise its ``expression`` must be a
    plain aggregate (``sum``, ``avg``, ``min``, ``max``, ``count``,
    ``count(distinct ...)``, ``count(*)``) over one column of the fact.

    Args:
        model: The fact the measure is declared on.
        measure: The measure entry from the spec.

    Returns:
        The DAX expression, or None when it cannot be translated.
    """
    if str(measure.get("dax") or "").strip():
        return " ".join(str(measure["dax"]).split())
    match = MEASURE_PATTERN.match(str(measure.get("expression") or ""))
    if not match:
        return None
    table = f"'{model.name}'"
    func = match.group("func").lower()
    column = match.group("column")
    if column == "*":
        return f"COUNTROWS({table})" if func == "count" else None
    known = {c.name.lower(): c.name for c in model.columns}
    known[model.surrogate_key.lower()] = model.surrogate_key
    if column.lower() not in known:
        return None
    ref = f"{table}[{known[column.lower()]}]"
    if func == "count" and match.group("distinct"):
        return f"DISTINCTCOUNT({ref})"
    if match.group("distinct"):
        return None
    return f"{DAX_FUNCTIONS[func]}({ref})"


def relationships(project: Project) -> List[Tuple[Model, str, Model, bool]]:
    """Return the fact -> dimension relationships.

    Args:
        project: The loaded project.

    Returns:
        (fact, key column, dimension, active). When a table points to the
        same dimension more than once (role playing), only the first is
        active.
    """
    out = []
    for model in project.gold():
        seen = set()
        for col in model.columns:
            dim = project.models.get(col.references or "")
            if not dim or dim.kind != "dimension":
                continue
            if col.pii and project.config.ai_pii == "exclude":
                continue
            out.append((model, col.name, dim, dim.key not in seen))
            seen.add(dim.key)
    return out


def _uid(project: Project, *parts: str) -> str:
    """Return a lineage tag that is the same on every render."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f"fde:{project.config.project}:" + ":".join(parts)))


def _name(text: str) -> str:
    """Quote a TMDL object name when it is not a plain identifier."""
    return text if IDENTIFIER.match(text) else "'" + text.replace(
        "'", "''") + "'"


def _doc(text: str, indent: str) -> List[str]:
    """Return ``///`` description lines for a TMDL object."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    return [f"{indent}/// {ln}" for ln in lines]


def _tmdl_type(data_type: str) -> Tuple[str, Optional[str]]:
    """Map a Warehouse type to a TMDL data type and format string.

    Args:
        data_type: e.g. ``decimal(18,2)``.

    Returns:
        (dataType, formatString or None).
    """
    base = data_type.split("(")[0].lower()
    if base in ("varchar", "char", "uniqueidentifier"):
        return "string", None
    if base == "bit":
        return "boolean", None
    if base in ("smallint", "int", "bigint"):
        return "int64", "0"
    if base in ("decimal", "numeric"):
        return "decimal", "#,0.00"
    if base in ("float", "real"):
        return "double", "#,0.00"
    if base == "date":
        return "dateTime", "Long Date"
    if base == "datetime2":
        return "dateTime", "General Date"
    return "string", None


def table_tmdl(project: Project, model: Model) -> str:
    """Render one table of the semantic model.

    Args:
        project: The loaded project.
        model: A gold model.

    Returns:
        TMDL text (tab indented).
    """
    t = TAB
    description = with_synonyms(model.description, model.synonyms)
    if model.ai_instructions:
        description = f"{description} Guidance: {model.ai_instructions}"
    lines = _doc(description, "")
    lines += [f"table {_name(model.name)}",
              f"{t}lineageTag: {_uid(project, 'table', model.key)}",
              f"{t}sourceLineageTag: [{model.schema}].[{model.name}]", ""]
    for measure in model.measures:
        dax = measure_dax(model, measure)
        if not measure.get("name") or dax is None:
            continue
        lines += _doc(with_synonyms(measure.get("description", ""),
                                    measure.get("synonyms")), t)
        lines.append(f"{t}measure {_name(str(measure['name']))} = {dax}")
        if measure.get("format"):
            lines.append(f"{t}{t}formatString: {measure['format']}")
        lines.append(f"{t}{t}lineageTag: "
                     f"{_uid(project, 'measure', model.key, measure['name'])}")
        lines.append("")
    for col in model_columns(project, model):
        data_type, fmt = _tmdl_type(col.data_type)
        lines += _doc(col.description, t)
        lines.append(f"{t}column {_name(col.name)}")
        lines.append(f"{t}{t}dataType: {data_type}")
        if fmt:
            lines.append(f"{t}{t}formatString: {fmt}")
        if col.hidden:
            lines.append(f"{t}{t}isHidden")
        lines += [f"{t}{t}lineageTag: "
                  f"{_uid(project, 'column', model.key, col.name)}",
                  f"{t}{t}summarizeBy: none",
                  f"{t}{t}sourceColumn: {col.name}", ""]
    lines += [f"{t}partition {_name(model.name)} = entity",
              f"{t}{t}mode: directLake",
              f"{t}{t}source",
              f"{t}{t}{t}entityName: {model.name}",
              f"{t}{t}{t}schemaName: {model.schema}",
              f"{t}{t}{t}expressionSource: DatabaseQuery", ""]
    return "\n".join(lines)


def relationships_tmdl(project: Project) -> str:
    """Render ``relationships.tmdl``.

    Args:
        project: The loaded project.

    Returns:
        TMDL text, empty when no gold column declares ``references:``.
    """
    t = TAB
    lines: List[str] = []
    for fact, column, dim, active in relationships(project):
        lines += [
            f"relationship {_uid(project, 'rel', fact.key, column)}",
            f"{t}fromColumn: {_name(fact.name)}.{_name(column)}",
            f"{t}toColumn: {_name(dim.name)}.{_name(dim.surrogate_key)}"]
        if not active:
            lines.append(f"{t}isActive: false")
        lines.append("")
    return "\n".join(lines)


def render_semantic_model(project: Project, platform) -> Dict[str, str]:
    """Render every file of the semantic model item.

    Args:
        project: The loaded project.
        platform: Function that returns a ``.platform`` file
            (``platform(project, item_type, name, description)``).

    Returns:
        Relative path -> content. Empty when the project has no gold table.
    """
    gold = project.gold()
    if not gold:
        return {}
    name = project.config.semantic_model
    base = f"fabric/{name}.SemanticModel"
    t = TAB
    out: Dict[str, str] = {}
    out[f"{base}/.platform"] = platform(
        project, "SemanticModel", name,
        "Direct Lake semantic model over the gold Warehouse.")
    out[f"{base}/definition.pbism"] = json.dumps({
        "$schema": ("https://developer.microsoft.com/json-schemas/fabric/"
                    "item/semanticModel/definitionProperties/1.0.0/"
                    "schema.json"),
        "version": "4.0", "settings": {}}, indent=2) + "\n"
    out[f"{base}/definition/database.tmdl"] = (
        f"database {_name(name)}\n{t}compatibilityLevel: 1604\n")
    model_lines = ["model Model", f"{t}culture: en-US",
                   f"{t}defaultPowerBIDataSourceVersion: powerBI_V3",
                   f"{t}discourageImplicitMeasures", ""]
    model_lines += [f"ref table {_name(m.name)}" for m in gold]
    model_lines += ["ref expression DatabaseQuery", ""]
    out[f"{base}/definition/model.tmdl"] = "\n".join(model_lines)
    out[f"{base}/definition/expressions.tmdl"] = "\n".join([
        "expression DatabaseQuery =",
        f"{t}{t}let",
        f"{t}{t}    database = Sql.Database(\"{SQL_ENDPOINT_PLACEHOLDER}\", "
        f"\"{WAREHOUSE_PLACEHOLDER}\")",
        f"{t}{t}in",
        f"{t}{t}    database",
        f"{t}lineageTag: {_uid(project, 'expression', 'DatabaseQuery')}",
        ""])
    if relationships(project):
        out[f"{base}/definition/relationships.tmdl"] = \
            relationships_tmdl(project)
    for model in gold:
        out[f"{base}/definition/tables/{model.name}.tmdl"] = table_tmdl(
            project, model)
    return out
