"""Render Fabric Data Agents from ``models/agents/<Name>.yml``.

A Data Agent answers business questions in natural language, over the gold
Warehouse and/or the semantic model. The spec holds what a person must
decide (instructions, which tables the agent may see, example questions);
this module writes the Fabric Git files from it::

    fabric/da_<name>.DataAgent/.platform
    fabric/da_<name>.DataAgent/Files/Config/data_agent.json
    fabric/da_<name>.DataAgent/Files/Config/draft/stage_config.json
    fabric/da_<name>.DataAgent/Files/Config/draft/<source folder>/datasource.json
    fabric/da_<name>.DataAgent/Files/Config/draft/<source folder>/fewshots.json

Only the ``draft`` stage is rendered. Publishing is a human step in Fabric
(the agent must be published before Copilot or Copilot Studio can use it).

Spec::

    description: What the agent is for.
    instructions: |                  # agent-level instructions (aiInstructions)
      Answer from the data only. Money is in rand.
    sources:
      - semantic_model: true         # the kit's own semantic model
        instructions: Use for totals and trends.
      - warehouse: true              # the gold Warehouse
        tables: [sales.FactNewBusiness]
        instructions: Use for row-level detail.
    examples:                        # question -> T-SQL over {{ ref() }}
      - question: How many policies were issued per product?
        query: |
          select ProductCode, count(*) as PolicyCount
          from {{ ref('sales.FactNewBusiness') }}
          group by ProductCode

Facts that decide how this is built (Microsoft Learn, Data Agent source
control, checked 2026-11):

* A data agent can select tables, not columns. A selected table exposes all
  its columns, so a warehouse source never includes a table with PII columns
  (check rule A5). The semantic model leaves PII columns out, so it is the
  safe source for tables that have them.
* A semantic model source does not support example queries, so ``examples``
  belong to the warehouse source.

[Spike] The item type ``DataAgent`` is in preview. Confirm the file names,
the ``datasource.json`` schema URL and the ``fabric-cicd`` placeholders for
the version you pin.
"""

from __future__ import annotations

import json
import uuid
from typing import Dict, List, Tuple

from fde import semantic
from fde.project import Agent, Model, Project

SCHEMA_ROOT = ("https://developer.microsoft.com/json-schemas/fabric/item/"
               "dataAgent/definition")


def _schema(name: str, version: str) -> str:
    """Return a Data Agent JSON schema URL."""
    return f"{SCHEMA_ROOT}/{name}/{version}/schema.json"


def _dump(data: dict) -> str:
    """Return JSON text that is the same on every render."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def warehouse_source(agent: Agent) -> dict:
    """Return the agent's warehouse source, or an empty dict.

    Args:
        agent: The agent.

    Returns:
        The ``sources:`` entry with ``warehouse``, or ``{}``.
    """
    for source in agent.sources:
        if source.get("warehouse"):
            return source
    return {}


def semantic_source(agent: Agent) -> dict:
    """Return the agent's semantic model source, or an empty dict.

    Args:
        agent: The agent.

    Returns:
        The ``sources:`` entry with ``semantic_model``, or ``{}``.
    """
    for source in agent.sources:
        if source.get("semantic_model"):
            return source
    return {}


def selected_tables(project: Project, source: dict) -> List[Model]:
    """Return the gold tables a warehouse source selects.

    Args:
        project: The loaded project.
        source: The warehouse ``sources:`` entry.

    Returns:
        Known gold models, in the order written.
    """
    return [project.models[k] for k in source.get("tables") or []
            if k in project.models and project.models[k].layer == "gold"]


def example_sql(project: Project, example: dict) -> str:
    """Return an example query as T-SQL with real table names.

    Args:
        project: The loaded project.
        example: One ``examples:`` entry.

    Returns:
        The query with ``{{ ref() }}`` resolved, no trailing semicolon, and
        Unix line endings.
    """
    text = str(example.get("query") or "").replace("\r\n", "\n").strip()
    return project.resolve_sql(text, "tsql").rstrip(";").strip()


def _guidance(project: Project, models: List[Model]) -> str:
    """Return the table guidance of the given models as one paragraph."""
    lines = [f"{m.name}: {m.ai_instructions}" for m in models
             if m.ai_instructions]
    return ("Table guidance. " + " ".join(lines)) if lines else ""


def _stage_config(project: Project, agent: Agent) -> str:
    """Return ``stage_config.json`` (the agent-level instructions)."""
    gold = [m for m in project.gold()]
    parts = [agent.instructions]
    guide = _guidance(project, gold)
    if guide:
        parts.append(guide)
    return _dump({"$schema": _schema("stageConfiguration", "1.0.0"),
                  "aiInstructions": "\n\n".join(parts)})


def _warehouse_elements(project: Project, selected: List[Model]) -> list:
    """Return the schema map of the gold Warehouse (every table listed)."""
    chosen = {m.key for m in selected}
    schemas: Dict[str, list] = {}
    for model in project.gold():
        columns = [{
            "display_name": c.name, "type": "warehouse_tables.column",
            "data_type": c.data_type, "is_selected": True,
            "description": c.description}
            for c in semantic.model_columns(project, model)]
        schemas.setdefault(model.schema, []).append({
            "display_name": model.name, "type": "warehouse_tables.table",
            "is_selected": model.key in chosen,
            "description": semantic.with_synonyms(model.description,
                                                  model.synonyms),
            "children": columns})
    return [{"display_name": schema, "type": "warehouse_tables.schema",
             "is_selected": any(t["is_selected"] for t in tables),
             "children": tables}
            for schema, tables in sorted(schemas.items())]


def _semantic_elements(project: Project) -> list:
    """Return the schema map of the semantic model."""
    out = []
    for model in project.gold():
        children = [{
            "display_name": c.name, "type": "semantic_model.column",
            "data_type": c.data_type, "is_selected": True,
            "description": c.description}
            for c in semantic.model_columns(project, model) if not c.hidden]
        for measure in model.measures:
            if semantic.measure_dax(model, measure) is None:
                continue
            children.append({
                "display_name": str(measure["name"]),
                "type": "semantic_model.measure", "is_selected": True,
                "description": semantic.with_synonyms(
                    measure.get("description", ""),
                    measure.get("synonyms"))})
        out.append({"display_name": model.name,
                    "type": "semantic_model.table", "is_selected": True,
                    "description": semantic.with_synonyms(
                        model.description, model.synonyms),
                    "children": children})
    return out


def _fewshots(project: Project, agent: Agent) -> str:
    """Return ``fewshots.json`` of the warehouse source."""
    shots = []
    for example in agent.examples:
        ident = uuid.uuid5(uuid.NAMESPACE_URL, (
            f"fde:{project.config.project}:{agent.name}:"
            f"{example.get('question')}"))
        shots.append({"id": str(ident),
                      "question": str(example.get("question") or "").strip(),
                      "query": example_sql(project, example)})
    return _dump({"$schema": _schema("fewShots", "1.0.0"),
                  "fewShots": shots})


def render_agent(project: Project, agent: Agent,
                 platform) -> Dict[str, str]:
    """Render every file of one Data Agent item.

    Args:
        project: The loaded project.
        agent: The agent.
        platform: Function that returns a ``.platform`` file
            (``platform(project, item_type, name, description)``).

    Returns:
        Relative path -> content.
    """
    base = f"fabric/{agent.item_name}.DataAgent"
    config = f"{base}/Files/Config"
    out: Dict[str, str] = {}
    out[f"{base}/.platform"] = platform(project, "DataAgent",
                                        agent.item_name, agent.description)
    out[f"{config}/data_agent.json"] = _dump({
        "$schema": _schema("dataAgent", "2.1.0")})
    out[f"{config}/draft/stage_config.json"] = _stage_config(project, agent)
    warehouse = warehouse_source(agent)
    if warehouse:
        name = project.config.gold_warehouse
        folder = f"{config}/draft/warehouse-tables-{name}"
        out[f"{folder}/datasource.json"] = _dump({
            "$schema": _schema("dataSource", "1.0.0"),
            "artifactId": semantic.WAREHOUSE_PLACEHOLDER,
            "workspaceId": "00000000-0000-0000-0000-0000000000a0",
            "displayName": name, "type": "data_warehouse",
            "userDescription": "Gold layer of the data warehouse.",
            "dataSourceInstructions": str(
                warehouse.get("instructions") or "").strip(),
            "elements": _warehouse_elements(
                project, selected_tables(project, warehouse))})
        out[f"{folder}/fewshots.json"] = _fewshots(project, agent)
    model = semantic_source(agent)
    if model:
        name = project.config.semantic_model
        folder = f"{config}/draft/semantic-model-{name}"
        out[f"{folder}/datasource.json"] = _dump({
            "$schema": _schema("dataSource", "1.0.0"),
            "artifactId": semantic.SEMANTIC_MODEL_PLACEHOLDER,
            "workspaceId": "00000000-0000-0000-0000-0000000000a0",
            "displayName": name, "type": "semantic_model",
            "userDescription": "Direct Lake semantic model over gold.",
            "dataSourceInstructions": str(
                model.get("instructions") or "").strip(),
            "elements": _semantic_elements(project)})
    return out


def render_agents(project: Project, platform) -> Dict[str, str]:
    """Render every Data Agent in the project.

    Args:
        project: The loaded project.
        platform: The ``.platform`` writer.

    Returns:
        Relative path -> content.
    """
    out: Dict[str, str] = {}
    for agent in project.agents.values():
        out.update(render_agent(project, agent, platform))
    return out


def run_examples(project: Project, agent: Agent,
                 connection) -> List[Tuple[str, bool, str]]:
    """Run an agent's example queries read-only and check each one.

    An example passes when it runs and returns at least one row (set
    ``allow_empty: true`` on the example to accept none). When the example
    lists ``expect_columns``, those columns must be in the result.

    Args:
        project: The loaded project.
        agent: The agent.
        connection: Open Warehouse connection.

    Returns:
        (question, passed, detail) per example.
    """
    from fde import connect

    results = []
    for example in agent.examples:
        question = str(example.get("question") or "")
        try:
            rows = connect.read_only_query(
                connection, example_sql(project, example), 200)
        except Exception as exc:  # the warehouse error is the finding
            results.append((question, False, f"query failed: {exc}"))
            continue
        if not rows and not example.get("allow_empty"):
            results.append((question, False, "returned no rows"))
            continue
        missing = [c for c in example.get("expect_columns") or []
                   if rows and c not in rows[0]]
        if missing:
            results.append((question, False,
                            f"missing columns: {', '.join(missing)}"))
            continue
        results.append((question, True, f"{len(rows)} rows"))
    return results
