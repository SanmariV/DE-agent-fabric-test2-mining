"""Project checks: layer rules, spec completeness, naming and data types.

This replaces dbt's parser errors, ``check_layers.py`` and
``dbt_project_evaluator``. Every finding names its rule; the rules are
listed in ``fabric_engineering_standards.md`` (section 12) with the reason.
``error`` findings fail ``python -m fde check``; ``warn`` findings are
reported and need a decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from fde import agent as agents
from fde import dq, semantic
from fde.project import (AUDIT_COLUMNS, REF_PATTERN, SCD_COLUMNS, Model,
                         Project, identifiers, rel)

SPARK_TYPES = re.compile(
    r"^(string|boolean|smallint|int|bigint|double|float|date|timestamp|"
    r"timestamp_ntz|binary|decimal\(\d+,\s*\d+\))$")
TSQL_TYPES = re.compile(
    r"^(varchar\((\d+|max)\)|char\(\d+\)|bit|smallint|int|bigint|"
    r"decimal\(\d+,\s*\d+\)|numeric\(\d+,\s*\d+\)|float|real|date|"
    r"time\(\d\)|datetime2\([0-6]\)|varbinary\((\d+|max)\)|uniqueidentifier)$")
TSQL_UNSUPPORTED = {"nvarchar", "nchar", "ntext", "text", "image", "datetime",
                    "smalldatetime", "datetimeoffset", "money", "smallmoney",
                    "tinyint", "xml", "sql_variant", "geography", "geometry",
                    "hierarchyid", "json"}
PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
COLUMN = re.compile(r"^[A-Z][A-Za-z0-9]*(_BK|_SK)?$")
SCHEMA = re.compile(r"^[a-z][a-z0-9_]*$")
ABBREVIATIONS = {
    "Amt": "Amount", "Qty": "Quantity", "Cust": "Customer",
    "Desc": "Description", "Nbr": "Number", "Num": "Number", "No": "Number",
    "Addr": "Address", "Dt": "Date", "Cd": "Code", "Acct": "Account",
    "Prem": "Premium", "Txn": "Transaction", "Trx": "Transaction",
    "Cnt": "Count", "Pct": "Percentage", "Dept": "Department",
    "Mgr": "Manager", "Prod": "Product", "Dob": "BirthDate",
    "Val": "Value", "Tel": "Telephone", "Src": "Source", "Tgt": "Target",
    "Tmp": "Temporary", "Misc": "Miscellaneous", "Flg": "Flag",
    "Ind": "Indicator", "Sts": "Status", "Stat": "Status", "Typ": "Type",
}
PII_HINT = re.compile(
    r"(First|Last|Middle|Full|Sur|Given|Family|Customer|Client|Member|"
    r"Policyholder|Person|Contact|Employee|Agent)Name|Surname|Email|Phone|"
    r"Mobile|Address|PostalCode|ZipCode|Birth|IdNumber|NationalId|Passport|"
    r"TaxNumber|Gender|^Age$|AgeYears", re.I)
RESERVED = set(AUDIT_COLUMNS) | set(SCD_COLUMNS)


@dataclass
class Finding:
    """One check result.

    Attributes:
        rule: Rule id, e.g. ``L1``.
        severity: ``error`` or ``warn``.
        file: Spec or SQL file (relative path).
        message: What is wrong and how to fix it.
    """

    rule: str
    severity: str
    file: str
    message: str


def _words(name: str) -> List[str]:
    """Split a PascalCase name into words.

    Args:
        name: e.g. ``PolicyStatusCode_BK``.

    Returns:
        e.g. ``['Policy', 'Status', 'Code']``.
    """
    base = re.sub(r"_(BK|SK)$", "", name)
    return re.findall(r"[A-Z][a-z0-9]*|[A-Z]+(?![a-z])", base)


def run_checks(project: Project) -> List[Finding]:
    """Run every check on the project.

    Args:
        project: The loaded project.

    Returns:
        Findings, errors first.
    """
    root = project.config.root
    out: List[Finding] = [Finding("P0", "error", f, m)
                          for f, m in project.errors]
    project_items = [project.config.bronze_lakehouse,
                     project.config.silver_lakehouse,
                     project.config.gold_warehouse]
    hard_coded = re.compile(
        r"\b(" + "|".join(re.escape(i) for i in project_items) + r")\s*\.",
        re.I)

    def add(rule: str, severity: str, path, message: str) -> None:
        out.append(Finding(rule, severity, rel(path, root), message))

    # Sources --------------------------------------------------------------
    for source in project.sources.values():
        if not source.description:
            add("S1", "error", source.path,
                f"source {source.name} has no description")
        if not source.freshness.get("loaded_at_column"):
            add("S7", "warn", source.path,
                f"source {source.name} has no freshness rule "
                "(loaded_at_column, warn_after_hours, error_after_hours)")
        for table in source.tables.values():
            if not table.description:
                add("S1", "warn", source.path,
                    f"{source.name}.{table.name}: no description")
            if not table.columns:
                add("S8", "error", source.path,
                    f"{source.name}.{table.name}: no columns; run "
                    f"python -m fde generate-source {source.name}")

    # Bronze tables read by more than one silver table (1:1 rule) ---------
    readers: dict = {}
    for model in project.silver():
        if model.source:
            readers.setdefault(model.source, []).append(model.key)
    for (source, table), keys in readers.items():
        if len(keys) > 1:
            add("L6", "error", project.models[keys[0]].path,
                f"bronze {source}.{table} feeds {', '.join(keys)}; one "
                "silver source table per bronze table")
    for source in project.sources.values():
        for table in source.tables:
            if (source.name, table) not in readers:
                add("L7", "warn", source.path,
                    f"bronze {source.name}.{table} has no silver table yet")

    silver_schemas = {m.schema for m in project.silver() if m.kind == "source"}
    integrated_schemas = {m.schema for m in project.silver()
                          if m.kind == "integrated"}
    for schema in silver_schemas & integrated_schemas:
        add("N5", "error", root / "models" / "silver" / schema,
            f"schema '{schema}' holds both source and integrated silver "
            "tables; use the source name for one and a domain for the other")

    gold_names: dict = {}
    for model in project.gold():
        gold_names.setdefault(model.name, []).append(model.key)
    for name, keys in gold_names.items():
        if len(keys) > 1:
            add("G5", "error", project.models[keys[0]].path,
                f"{name} exists in several schemas ({', '.join(keys)}); one "
                "concept, one gold table")

    for model in project.silver() + project.gold():
        out.extend(_model_checks(project, model, hard_coded))

    # Tests -------------------------------------------------------------
    for test in dq.all_tests(project):
        model = project.models.get(test.table)
        path = model.path if model else root / "models"
        if test.severity not in dq.SEVERITIES:
            add("T1", "error", path, f"{test.table} {test.name}: severity "
                f"must be error or warn, not '{test.severity}'")
        allowed = dq.COLUMN_TESTS if test.column else dq.TABLE_TESTS
        if not test.implied and test.kind not in allowed:
            add("T1", "error", path,
                f"{test.table}: unknown {'column' if test.column else 'table'}"
                f" test '{test.kind}'. Allowed: {', '.join(sorted(allowed))}")
            continue
        if test.kind == "accepted_values" and not test.args.get("values"):
            add("T2", "error", path, f"{test.table} {test.name}: "
                "accepted_values needs a non-empty values list")
        if test.kind in ("relationships", "reconciles_to"):
            other = str(test.args.get("to") or test.args.get("compare_to"))
            if other not in project.models:
                add("T3", "error", path, f"{test.table} {test.name}: "
                    f"'{other}' is not a model (use schema.Table)")
        if test.kind == "expression" and not (test.args.get("expression")
                                              or test.args.get("value")):
            add("T2", "error", path, f"{test.table} {test.name}: "
                "expression test needs an expression")
    out.extend(_ai_checks(project))
    order = {"error": 0, "warn": 1}
    return sorted(out, key=lambda f: (order.get(f.severity, 2), f.file,
                                      f.rule))


def _ai_checks(project: Project) -> List[Finding]:
    """Check what the semantic model and the Data Agents are built from.

    Args:
        project: The loaded project.

    Returns:
        Findings (rules A1-A7).
    """
    root = project.config.root
    out: List[Finding] = []

    def add(rule: str, severity: str, path, message: str) -> None:
        out.append(Finding(rule, severity, rel(path, root), message))

    gold = project.gold()
    for model in project.silver() + gold:
        pairs = [(model.key, model.spec.get("synonyms"))]
        pairs += [(f"{model.key}.{c.name}", c.synonyms)
                  for c in model.columns]
        pairs += [(f"{model.key}.{m.get('name')}", m.get("synonyms"))
                  for m in model.measures]
        for label, value in pairs:
            if value not in (None, [], "") and (
                    not isinstance(value, list)
                    or not all(isinstance(v, str) and v.strip()
                               for v in value)):
                add("A2", "error", model.path, f"{label}: synonyms must be "
                    "a list of words, e.g. synonyms: ['Premium', 'GWP']")
        if model.spec.get("ai_instructions") not in (None, "") and                 not model.ai_instructions:
            add("A2", "error", model.path, f"{model.key}: ai_instructions "
                "must be text")
        for measure in model.measures:
            if measure.get("name") and measure.get("expression") and                     semantic.measure_dax(model, measure) is None:
                add("A1", "error", model.path, f"{model.key}: measure "
                    f"{measure['name']} cannot be turned into DAX. Use a "
                    "plain sum/avg/min/max/count over one column of the "
                    "fact, or write the DAX yourself in `dax:`")
    if gold and not any(m.measures for m in gold):
        add("A7", "warn", root / "models" / "gold",
            "no fact declares measures; the semantic model will have none "
            "and AI items can only list rows, not answer 'how much'")

    known = set(project.models)
    for agent in project.agents.values():
        def fail(rule: str, message: str, severity: str = "error") -> None:
            add(rule, severity, agent.path, f"{agent.name}: {message}")

        if not agent.description:
            fail("A3", "no description")
        if not agent.instructions:
            fail("A3", "no instructions (what the agent is for, what it "
                 "must never do, how to word answers)")
        if not agent.sources:
            fail("A3", "no sources; add semantic_model and/or warehouse")
        warehouse = agents.warehouse_source(agent)
        if not (warehouse or agents.semantic_source(agent)):
            fail("A3", "sources must include `semantic_model: true` or "
                 "`warehouse: true`")
        tables = list(warehouse.get("tables") or [])
        if warehouse and not tables:
            fail("A4", "the warehouse source selects no tables")
        for key in tables:
            model = project.models.get(key)
            if not model or model.layer != "gold":
                fail("A4", f"'{key}' is not a gold table (use schema.Table)")
            elif any(c.pii for c in model.columns):
                names = ", ".join(c.name for c in model.columns if c.pii)
                fail("A5", f"{key} has personal data ({names}) and a data "
                     "agent cannot hide single columns. Remove the table "
                     "from the warehouse source and use the semantic model "
                     "(it leaves PII out), or split the PII into its own "
                     "table")
        if agent.examples and not warehouse:
            fail("A4", "examples need a warehouse source (a semantic "
                 "model source does not support example queries)")
        if warehouse and len(agent.examples) < 3:
            fail("A6", f"{len(agent.examples)} example question(s); give "
                 "3 or more, covering the questions people ask most",
                 "warn")
        for example in agent.examples:
            question = str(example.get("question") or "").strip()
            query = str(example.get("query") or "")
            if not question or not query.strip():
                fail("A4", "every example needs a question and a query")
                continue
            refs = [m.group("key") for m in REF_PATTERN.finditer(query)]
            for key in refs:
                if key not in known:
                    fail("A4", f"'{question}': ref('{key}') is not a model")
                elif key not in tables:
                    fail("A4", f"'{question}': reads {key}, which the "
                         "warehouse source does not select")
            if not refs:
                fail("A4", f"'{question}': read tables with "
                     "{{ ref('schema.Table') }}")
            sql = agents.example_sql(project, example)
            try:
                from fde import connect
                connect.assert_read_only(sql)
            except Exception as exc:
                fail("A4", f"'{question}': {exc}")
            else:
                try:
                    import sqlglot
                    sqlglot.parse_one(sql, read="tsql")
                except ImportError:
                    pass
                except Exception as exc:
                    fail("A4", f"'{question}': not valid T-SQL: "
                         f"{str(exc).splitlines()[0]}")
    return out


def _model_checks(project: Project, model: Model,
                  hard_coded: re.Pattern) -> List[Finding]:
    """Run the checks for one silver or gold model.

    Args:
        project: The loaded project.
        model: The model.
        hard_coded: Pattern matching hard-coded item names.

    Returns:
        Findings for this model.
    """
    root = project.config.root
    out: List[Finding] = []
    sql_file = model.path.with_suffix(".sql")

    def add(rule: str, severity: str, message: str, path=None) -> None:
        out.append(Finding(rule, severity, rel(path or model.path, root),
                           f"{model.key}: {message}"))

    # Structure -------------------------------------------------------------
    if not SCHEMA.match(model.schema):
        add("N4", "error", "schema (folder) names are lower snake_case")
    if not PASCAL.match(model.name):
        add("N1", "error", "table names are PascalCase, singular")
    if not model.description:
        add("S1", "error", "no description")
    elif not re.search(r"grain\s*=", model.description, re.I):
        add("S2", "error", "description must state the grain "
            "('Grain = <key columns>')")
    if not model.columns:
        add("S3", "error", "no columns")
    if not model.business_keys:
        add("S4", "error", "no business key; mark the key column(s) "
            "business_key: true (DE Policy v2: every table has a logical "
            "primary key)")

    if model.layer == "silver":
        if re.match(r"^(Dim|Fact|Bridge)[A-Z]", model.name):
            add("N2", "error", "Dim/Fact prefixes are for gold tables only")
        if model.kind == "source" and not model.source:
            add("L1", "error", "source must be {source: <source>, table: "
                "<bronze table>}")
        elif model.kind == "source":
            source, table = model.source
            bronze = project.sources.get(source)
            if not bronze or table not in bronze.tables:
                add("L1", "error", f"source {source}.{table} is not declared "
                    "in models/sources/")
            else:
                known = {c.lower() for c in bronze.tables[table].columns}
                for col in model.columns:
                    expr = col.expression or col.name
                    tokens = [t for t in identifiers(str(expr))
                              if t in known]
                    if not col.expression:
                        add("S5", "error", f"{col.name}: no expression "
                            "(the bronze column or Spark SQL it comes from)")
                    elif not tokens:
                        add("S5", "warn", f"{col.name}: expression uses no "
                            "bronze column; check the column names")
            if model.sql:
                add("L2", "error", "a silver source table is built from its "
                    "spec only; delete the .sql file", sql_file)
            if model.load.get("mode") == "incremental" and \
                    not model.load.get("column"):
                add("S6", "error", "incremental load needs load.column")
        else:
            if not model.sql:
                add("S9", "error", "integrated silver table needs a .sql "
                    "SELECT next to its spec", sql_file)
            for ref in model.refs:
                target = project.models.get(ref)
                if target and target.layer != "silver":
                    add("L3", "error", f"reads {ref}; silver never reads "
                        "gold", sql_file)
    else:
        if model.kind == "unknown":
            add("N2", "error", "gold table names start with Dim, Fact or "
                "Bridge")
        if model.kind == "dimension" and model.scd_type not in (1, 2):
            add("G1", "error", "dimensions set scd_type: 1 or 2")
        if model.kind != "dimension" and model.scd_type:
            add("G1", "warn", "scd_type only applies to dimensions")
        if model.measures and model.kind != "fact":
            add("G4", "error", "measures belong on facts")
        if not model.sql:
            add("S9", "error", "gold table needs a .sql SELECT next to its "
                "spec", sql_file)
        if model.sql and re.search(r"@\w+", re.sub(r"--[^\n]*", "",
                                                   model.sql)):
            add("G6", "error", "the SELECT becomes a view and cannot use "
                "@parameters; use load.mode incremental for date windows",
                sql_file)
        if model.sql and re.search(r"\border\s+by\b", model.sql, re.I) and \
                not re.search(r"\bover\s*\(", model.sql, re.I):
            add("G7", "warn", "ORDER BY in a view is ignored; remove it",
                sql_file)
        for ref in model.refs:
            target = project.models.get(ref)
            if target and target.layer == "gold" and target.kind == "fact" \
                    and model.kind == "dimension":
                add("L4", "warn", f"dimension reads fact {ref}; check the "
                    "design", sql_file)
        if model.load.get("mode") == "incremental" and \
                not model.load.get("column"):
            add("S6", "error", "incremental load needs load.column")

    # SQL references -------------------------------------------------------
    if model.sql:
        body = re.sub(r"--[^\n]*", "", model.sql)
        if hard_coded.search(body):
            add("L5", "error", "hard-coded lakehouse/warehouse name; use "
                "{{ ref('schema.Table') }}", sql_file)
        if "{{ source(" in body.replace("{{source(", "{{ source("):
            add("L5", "error", "source() is only used by silver source "
                "tables (in the spec); read silver with ref()", sql_file)
        for match in REF_PATTERN.finditer(body):
            if match.group("key") not in project.models:
                add("L8", "error", f"ref('{match.group('key')}') is not a "
                    "model", sql_file)
        if model.key in model.refs:
            add("L8", "error", "the table reads itself", sql_file)
        if re.search(r"\b(getdate|sysdatetime|sysutcdatetime|newid|rand|"
                     r"current_timestamp|current_date|now)\s*\(", body, re.I):
            add("I1", "error", "non-deterministic function in the logic; "
                "pass dates in as load_date / the load procedure's @LoadDate",
                sql_file)

    # Columns -------------------------------------------------------------
    seen = set()
    types = SPARK_TYPES if model.layer == "silver" else TSQL_TYPES
    for col in model.columns:
        if not col.name:
            add("S3", "error", "a column has no name")
            continue
        if col.name.lower() in seen:
            add("S3", "error", f"{col.name}: declared twice")
        seen.add(col.name.lower())
        if col.name in RESERVED or col.name == model.surrogate_key:
            add("S10", "error", f"{col.name}: added by the kit; remove it "
                "from the spec")
            continue
        if not col.description:
            add("S1", "error", f"{col.name}: no description")
        elif str(col.description).strip().upper().startswith("TODO"):
            add("S1", "warn", f"{col.name}: {col.description}")
        dtype = col.data_type
        base = dtype.split("(")[0]
        if not dtype:
            add("D1", "error", f"{col.name}: no data_type")
        elif model.layer == "gold" and base in TSQL_UNSUPPORTED:
            add("D2", "error", f"{col.name}: {dtype} is not supported by the "
                "Fabric Warehouse (use varchar, datetime2(6), decimal, int)")
        elif not types.match(dtype):
            add("D1", "error", f"{col.name}: '{dtype}' is not an allowed "
                f"{'Spark' if model.layer == 'silver' else 'Warehouse'} type")
        elif base in ("float", "real", "double") and re.search(
                r"Amount|Amt|Premium|Prem|Price|Cost|Balance|Value|Total",
                col.name):
            add("D3", "error", f"{col.name}: money is decimal(18,2), never "
                "a floating type")
        if not COLUMN.match(col.name):
            add("N3", "error", f"{col.name}: column names are PascalCase "
                "(suffix _BK for business keys, _SK for surrogate keys)")
        if col.business_key and not col.name.endswith("_BK"):
            add("N6", "error", f"{col.name}: business key columns end "
                "with _BK")
        # A non-key column may end in _BK: it carries another entity's
        # business key (e.g. Agent_BK on Policy), named as in its own table.
        if col.name.endswith("_SK"):
            if model.layer == "silver":
                add("N7", "error", f"{col.name}: surrogate keys are gold only")
            elif not col.references:
                add("G2", "error", f"{col.name}: _SK column needs "
                    "references: <schema>.<DimTable>")
        if col.references:
            ref = project.models.get(col.references)
            if not ref or ref.kind != "dimension":
                add("G2", "error", f"{col.name}: references "
                    f"'{col.references}', which is not a gold dimension")
            elif not col.name.endswith(f"{ref.name}_SK"):
                add("G3", "error", f"{col.name}: a key to {ref.name} is "
                    f"named <Role>{ref.name}_SK")
            if col.data_type != "bigint":
                add("G3", "error", f"{col.name}: surrogate keys are bigint")
        words = _words(col.name)
        for word in words:
            if word in ABBREVIATIONS:
                add("N8", "warn", f"{col.name}: '{word}' is an abbreviation; "
                    f"use '{ABBREVIATIONS[word]}'")
        is_bool = base in ("boolean", "bit")
        if is_bool and not re.match(r"^(Is|Has)[A-Z]", col.name):
            add("N9", "error", f"{col.name}: boolean columns start with Is "
                "or Has")
        if re.match(r"^(Is|Has)[A-Z]", col.name) and not is_bool:
            add("N9", "error", f"{col.name}: Is/Has columns are boolean "
                f"({'boolean' if model.layer == 'silver' else 'bit'})")
        if col.name.endswith("Date") and base not in ("date",):
            add("N10", "error", f"{col.name}: ...Date columns are date")
        if re.search(r"(Timestamp|DateTime)$", col.name) and base not in (
                "timestamp", "timestamp_ntz", "datetime2"):
            add("N10", "error", f"{col.name}: ...Timestamp columns are "
                f"{'timestamp' if model.layer == 'silver' else 'datetime2(6)'}")
        if "pii" not in col.meta and PII_HINT.search(col.name):
            add("P1", "warn", f"{col.name}: looks like personal data; set "
                "meta.pii: true (or false) in the spec")
    for measure in model.measures:
        if not measure.get("name") or not measure.get("expression"):
            add("G4", "error", "each measure needs a name and an expression")
        elif not measure.get("description"):
            add("G4", "error", f"measure {measure['name']}: no description "
                "(it becomes the measure definition)")
        elif not PASCAL.match(str(measure["name"])):
            add("N3", "error", f"measure {measure['name']}: PascalCase")
    return out
