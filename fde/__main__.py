"""Command line: ``python -m fde <command>``.

Offline (no Fabric connection):
    parse          check the specs load and write target/manifest.json
    check          layer, naming, type and completeness rules + render drift
    render         write the notebooks, T-SQL, semantic model and agents
                   Fabric runs (--check: CI)
    ls             list models and tests
    build-common   build the fabric_de_common wheel for the Environment

Against a workspace (``--target dev`` by default):
    debug            test the connection and list the items it can see
    show             run one read-only SELECT (refs allowed)
    generate-source  write models/sources/<source>.yml from bronze metadata
    deploy           publish notebooks (fabric-cicd) and gold T-SQL;
                     --ai-only publishes the semantic model and Data Agents
    run-silver       run nb_ops_run_silver and wait for it
    test             run the data quality tests and print the results
    test-agent       run every Data Agent example question (read-only)
    build            deploy, run silver, load gold and test, layer by layer
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import List

import yaml

from fde import check as checks
from fde import agent, connect, dq, manifest, render
from fde.project import Project, load_project, rel

ROOT = Path.cwd()


def _project() -> Project:
    """Load the project from the current folder.

    Returns:
        The project.
    """
    return load_project(ROOT)


def _table(rows: List[dict], limit: int = 50) -> str:
    """Format rows as a plain-text table.

    Args:
        rows: Rows as dicts.
        limit: Maximum rows to show.

    Returns:
        The table text.
    """
    if not rows:
        return "(no rows)"
    names = list(rows[0])
    shown = [[str(r.get(n, "")) for n in names] for r in rows[:limit]]
    widths = [max(len(n), *(len(r[i]) for r in shown))
              for i, n in enumerate(names)]
    line = " | ".join(n.ljust(w) for n, w in zip(names, widths))
    out = [line, "-+-".join("-" * w for w in widths)]
    out += [" | ".join(v.ljust(w) for v, w in zip(r, widths)) for r in shown]
    return "\n".join(out)


def cmd_parse(args) -> int:
    """Load every spec and write the manifest.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    for path, message in project.errors:
        print(f"error: {path}: {message}")
    path = manifest.write(project)
    print(f"{len(project.sources)} sources, {len(project.silver())} silver, "
          f"{len(project.gold())} gold, {len(dq.all_tests(project))} tests. "
          f"Wrote {path}")
    return 1 if project.errors else 0


def cmd_check(args) -> int:
    """Run the project checks and the render drift check.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (1 when any error finding or drift).
    """
    project = _project()
    findings = checks.run_checks(project)
    drift = render.write(project, check=True)
    for f in findings:
        print(f"{f.severity:5} {f.rule:4} {f.file}: {f.message}")
    for message in drift:
        print(f"error R1   {message} (run python -m fde render)")
    errors = sum(f.severity == "error" for f in findings) + len(drift)
    warns = sum(f.severity == "warn" for f in findings)
    print(f"check: {errors} errors, {warns} warnings")
    return 1 if errors else 0


def cmd_render(args) -> int:
    """Write (or check) the rendered files.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    if project.errors:
        for path, message in project.errors:
            print(f"error: {path}: {message}")
        return 1
    messages = render.write(project, check=args.check)
    for message in messages:
        print(message)
    if args.check:
        print("render: up to date" if not messages
              else f"render: {len(messages)} files out of date")
        return 1 if messages else 0
    print(f"render: {len(messages)} files changed")
    return 0


def cmd_ls(args) -> int:
    """List models (and tests).

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    for source in project.sources.values():
        for table in source.tables:
            print(f"source  {source.name}.{table}")
    for model in project.silver() + project.gold():
        print(f"{model.layer:6}  {model.key:40} {model.kind:10} "
              f"keys={','.join(model.business_keys)}")
    if args.tests:
        for test in dq.all_tests(project):
            print(f"test    {test.table:40} {test.name:45} {test.severity}"
                  f"{' (implied)' if test.implied else ''}")
    return 0


def cmd_debug(args) -> int:
    """Test the connection to a target.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    with connect.sql_connection(project.config, args.target) as conn:
        info = connect.query(conn, "select db_name() as warehouse, "
                             "suser_sname() as signed_in_as")
        print(_table(info))
        items = connect.query(conn, "select name from sys.databases "
                              "order by name")
        print("Items this endpoint can query:",
              ", ".join(r["name"] for r in items))
        wanted = [project.config.bronze_lakehouse,
                  project.config.silver_lakehouse,
                  project.config.gold_warehouse]
        missing = [w for w in wanted if w not in {r["name"] for r in items}]
        if missing:
            print(f"Missing items (create them, or fix fde.yml): {missing}")
            return 1
    print("debug: connection OK")
    return 0


def cmd_show(args) -> int:
    """Run one read-only SELECT and print the rows.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    sql = project.resolve_sql(args.sql, "tsql")
    with connect.sql_connection(project.config, args.target) as conn:
        print(_table(connect.read_only_query(conn, sql, args.limit),
                     args.limit))
    return 0


def _sql_type(row: dict) -> str:
    """Format an INFORMATION_SCHEMA column type.

    Args:
        row: INFORMATION_SCHEMA.COLUMNS row.

    Returns:
        e.g. ``varchar(8000)`` or ``decimal(18,2)``.
    """
    base = row["DATA_TYPE"].lower()
    if base in ("varchar", "char", "varbinary", "nvarchar", "nchar"):
        length = row["CHARACTER_MAXIMUM_LENGTH"]
        return f"{base}({'max' if length == -1 else length})"
    if base in ("decimal", "numeric"):
        return f"{base}({row['NUMERIC_PRECISION']},{row['NUMERIC_SCALE']})"
    if base in ("datetime2", "time"):
        return f"{base}({row['DATETIME_PRECISION']})"
    return base


def cmd_generate_source(args) -> int:
    """Write ``models/sources/<source>.yml`` from the bronze metadata.

    Existing descriptions, freshness and meta are kept; new tables and
    columns are added; dropped ones are reported.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    schema = args.schema or args.source
    lakehouse = project.config.bronze_lakehouse
    sql = (f"select TABLE_NAME, COLUMN_NAME, DATA_TYPE, "
           "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
           f"DATETIME_PRECISION from [{lakehouse}].INFORMATION_SCHEMA.COLUMNS "
           f"where TABLE_SCHEMA = '{schema.replace(chr(39), '')}' "
           "order by TABLE_NAME, ORDINAL_POSITION")
    with connect.sql_connection(project.config, args.target) as conn:
        rows = connect.query(conn, sql)
    if not rows:
        print(f"No tables found in {lakehouse}.{schema}. Check the schema "
              "name and that the SQL endpoint has synced.")
        return 1
    path = ROOT / "models" / "sources" / f"{args.source}.yml"
    old = yaml.safe_load(path.read_text(encoding="utf-8")) \
        if path.exists() else {}
    old_tables = {t["name"]: t for t in (old or {}).get("tables") or []}
    defaults = (project.config.raw.get("defaults") or {}).get("freshness")
    tables = {}
    for row in rows:
        tables.setdefault(row["TABLE_NAME"], []).append(row)
    out_tables = []
    for name, cols in tables.items():
        before = old_tables.get(name, {})
        old_cols = {c["name"]: c for c in before.get("columns") or []
                    if isinstance(c, dict)}
        out_tables.append({
            "name": name,
            "description": before.get("description")
            or f"TODO(what one row of {name} is)",
            **({"meta": before["meta"]} if before.get("meta") else {}),
            "columns": [{**old_cols.get(c["COLUMN_NAME"], {}),
                         "name": c["COLUMN_NAME"],
                         "data_type": _sql_type(c)} for c in cols],
        })
        gone = set(old_cols) - {c["COLUMN_NAME"] for c in cols}
        if gone:
            print(f"warning: {name}: columns no longer in bronze: "
                  f"{sorted(gone)}")
    for name in set(old_tables) - set(tables):
        print(f"warning: table {name} is no longer in bronze; removed")
    doc = {
        "source": args.source,
        "description": (old or {}).get("description")
        or f"TODO(what the {args.source} system is and how it lands)",
        **({"schema": schema} if schema != args.source else {}),
        "freshness": (old or {}).get("freshness") or defaults or {
            "loaded_at_column": "_ingested_at", "warn_after_hours": 26,
            "error_after_hours": 48},
        "tables": out_tables,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, width=79,
                                   allow_unicode=True), encoding="utf-8")
    print(f"Wrote {rel(path, ROOT)}: {len(out_tables)} tables, "
          f"{len(rows)} columns")
    return 0


def _ordered_gold_files(project: Project) -> List[Path]:
    """Return the rendered gold files in deploy order.

    Args:
        project: The loaded project.

    Returns:
        Tables (ops first), then views, then procedures (ops last).
    """
    gold = ROOT / "gold"
    order = project.load_order(project.gold())
    files = [gold / "ops" / "tables" / "DataQualityResult.sql"]
    files += [gold / m.schema / "tables" / f"{m.name}.sql" for m in order]
    files += [gold / m.schema / "views" / f"{m.name}Source.sql"
              for m in order]
    files += [gold / m.schema / "procedures" / f"Load{m.name}.sql"
              for m in order]
    files += [gold / "ops" / "procedures" / "RunDataQualityTests.sql",
              gold / "ops" / "procedures" / "RunGoldLoads.sql"]
    return files


def _deploy(project: Project, target: str, notebooks: bool,
            sql: bool, ai: bool = False) -> None:
    """Publish notebooks, gold T-SQL and the AI items to a target.

    Args:
        project: The loaded project.
        target: Target name.
        notebooks: Publish the Fabric notebooks.
        sql: Run the gold T-SQL.
        ai: Publish the semantic model and the Data Agents. Run this after
            the gold tables exist: a Direct Lake model reads them.

    Raises:
        connect.TargetError: If the render is stale or settings are missing.
    """
    if render.write(project, check=True):
        raise connect.TargetError("rendered files are out of date; run "
                                  "python -m fde render first")
    settings = connect.target_settings(project.config, target, writes=True)
    if notebooks:
        if not settings["workspace_id"]:
            raise connect.TargetError(
                f"set {settings['workspace_id_env']} to the workspace id")
        try:
            from fabric_cicd import FabricWorkspace, publish_all_items
        except ImportError as exc:
            raise connect.TargetError(
                "pip install fabric-cicd (see requirements.txt)") from exc
        workspace = FabricWorkspace(
            workspace_id=settings["workspace_id"],
            environment=target.upper(),
            repository_directory=str(ROOT / "fabric"),
            item_type_in_scope=["Notebook"],
            token_credential=connect.credential())
        publish_all_items(workspace)
        print(f"deploy: notebooks published to {target}")
    if sql:
        with connect.sql_connection(project.config, target,
                                    writes=True) as conn:
            for path in _ordered_gold_files(project):
                batches = connect.execute_batches(
                    conn, path.read_text(encoding="utf-8"))
                print(f"deploy: {rel(path, ROOT)} ({batches} batches)")
    if ai:
        if not settings["workspace_id"]:
            raise connect.TargetError(
                f"set {settings['workspace_id_env']} to the workspace id")
        try:
            from fabric_cicd import FabricWorkspace, publish_all_items
        except ImportError as exc:
            raise connect.TargetError(
                "pip install fabric-cicd (see requirements.txt)") from exc
        scope = ["SemanticModel"] + (["DataAgent"] if project.agents else [])
        workspace = FabricWorkspace(
            workspace_id=settings["workspace_id"],
            environment=target.upper(),
            repository_directory=str(ROOT / "fabric"),
            item_type_in_scope=scope,
            token_credential=connect.credential())
        publish_all_items(workspace)
        print(f"deploy: {', '.join(scope)} published to {target}. "
              "Publish each Data Agent in Fabric before people use it.")


def cmd_deploy(args) -> int:
    """Publish to a target.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    if args.ai_only:
        _deploy(_project(), args.target, False, False, ai=True)
    else:
        _deploy(_project(), args.target, not args.sql_only,
                not args.notebooks_only, ai=args.ai)
    return 0


def _load_step(target: str) -> str:
    """Return a load step id for a manual run.

    Args:
        target: Target name.

    Returns:
        e.g. ``dev-20261104T101500Z`` (fits varchar(36)).
    """
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{target}-{stamp}"[:36]


def _run_silver(project: Project, target: str, load_date: str,
                load_step: str, full_refresh: bool) -> None:
    """Run the silver orchestration notebook and wait.

    Args:
        project: The loaded project.
        target: Target name.
        load_date: Business date (may be empty for yesterday).
        load_step: Load step id.
        full_refresh: Read all of bronze.
    """
    settings = connect.target_settings(project.config, target, writes=True)
    if not settings["workspace_id"]:
        raise connect.TargetError(
            f"set {settings['workspace_id_env']} to the workspace id")
    print(f"run-silver: nb_ops_run_silver on {target} ...")
    status = connect.run_notebook(settings["workspace_id"],
                                  "nb_ops_run_silver", {
                                      "load_date": load_date,
                                      "load_step_id": load_step,
                                      "full_refresh": str(full_refresh).lower()})
    print(f"run-silver: {status}")


def cmd_run_silver(args) -> int:
    """Run the silver layer on a target.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    _run_silver(_project(), args.target, args.load_date or "",
                _load_step(args.target), args.full_refresh)
    return 0


def _test(project: Project, conn, layer: str, select: str = "") -> int:
    """Run the tests of one layer and print the results.

    Args:
        project: The loaded project.
        conn: Open connection.
        layer: ``source``, ``silver`` or ``gold``.
        select: Only tests on tables whose key contains this text.

    Returns:
        The number of failed error-severity tests (SQL errors count).
    """
    failed = 0
    rows = []
    for test in dq.all_tests(project, layer):
        if select and select.lower() not in test.table.lower():
            continue
        try:
            count = connect.query(conn, dq.count_sql(project, test))[0][
                "failures"]
            status = "PASS" if not count else (
                "FAIL" if test.severity == "error" else "WARN")
        except Exception as exc:  # report every broken test, then fail
            count, status = str(exc).splitlines()[0][:80], "ERROR"
        if status in ("FAIL", "ERROR"):
            failed += 1
        rows.append({"status": status, "table": test.table,
                     "test": test.name, "failures": count})
    print(_table(rows, limit=10000))
    passed = sum(r["status"] == "PASS" for r in rows)
    print(f"test {layer}: {len(rows)} tests, {passed} pass, "
          f"{sum(r['status'] == 'WARN' for r in rows)} warn, {failed} fail")
    return failed


def cmd_test(args) -> int:
    """Run data quality tests on a target.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    layers = [args.layer] if args.layer != "all" else \
        ["source", "silver", "gold"]
    failed = 0
    with connect.sql_connection(project.config, args.target) as conn:
        for layer in layers:
            failed += _test(project, conn, layer, args.select or "")
    return 1 if failed else 0


def cmd_test_agent(args) -> int:
    """Run the example questions of every Data Agent, read-only.

    An example passes when its query runs on the Warehouse and returns rows.
    This tests the queries the agent is shown, not the agent's own answers:
    ask the agent the same questions in Fabric to compare.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (1 when any example fails).
    """
    project = _project()
    chosen = [a for a in project.agents.values()
              if not args.select or args.select.lower() in a.name.lower()]
    if not chosen:
        print("test-agent: no agents (models/agents/<Name>.yml)")
        return 1
    failed = 0
    with connect.sql_connection(project.config, args.target) as conn:
        for item in chosen:
            for question, passed, detail in agent.run_examples(
                    project, item, conn):
                failed += not passed
                print(f"{'pass' if passed else 'FAIL'}  {item.name}: "
                      f"{question} ({detail})")
    print(f"test-agent: {failed} failed")
    return 1 if failed else 0


def cmd_build(args) -> int:
    """Deploy, run and test the selected layers, stopping at a failure.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    project = _project()
    step = _load_step(args.target)
    load_date = args.load_date or (dt.date.today()
                                   - dt.timedelta(days=1)).isoformat()
    silver = args.layer in ("all", "silver")
    gold = args.layer in ("all", "gold")
    if not args.skip_deploy:
        _deploy(project, args.target, notebooks=silver, sql=True)
    with connect.sql_connection(project.config, args.target,
                                writes=True) as conn:
        if silver:
            if not args.skip_source_tests and _test(project, conn, "source"):
                print("build: stopped, source tests failed "
                      "(--skip-source-tests to continue in dev)")
                return 1
            _run_silver(project, args.target, load_date, step,
                        args.full_refresh)
            if _test(project, conn, "silver"):
                print("build: stopped, silver tests failed")
                return 1
        if gold:
            connect.execute_batches(
                conn, "EXEC [ops].[RunGoldLoads] @LoadDate = "
                      f"'{load_date}', @LoadStepID = '{step}'")
            print(f"build: gold loaded (LoadStepID {step})")
            if _test(project, conn, "gold"):
                print("build: gold tests failed")
                return 1
    print("build: OK")
    return 0


def cmd_build_common(args) -> int:
    """Build the fabric_de_common wheel.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    out = ROOT / "target" / "dist"
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT / "common"),
         "--no-deps", "-w", str(out)], check=False)
    if result.returncode == 0:
        print(f"Wheel in {rel(out, ROOT)}. Upload it to the Environment "
              "(START_HERE.md, step 5) and publish the Environment.")
    return result.returncode


def main(argv=None) -> int:
    """Parse arguments and run a command.

    Args:
        argv: Arguments (default: sys.argv).

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m fde",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text, target=False):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        if target:
            p.add_argument("--target", default="dev")
        return p

    add("parse", cmd_parse, "load specs, write target/manifest.json")
    add("check", cmd_check, "project rules and render drift")
    p = add("render", cmd_render, "write notebooks and T-SQL")
    p.add_argument("--check", action="store_true",
                   help="change nothing; fail when files are out of date")
    p = add("ls", cmd_ls, "list models")
    p.add_argument("--tests", action="store_true")
    add("build-common", cmd_build_common, "build the fabric_de_common wheel")
    add("debug", cmd_debug, "test the connection", target=True)
    p = add("show", cmd_show, "run one read-only SELECT", target=True)
    p.add_argument("sql")
    p.add_argument("--limit", type=int, default=50)
    p = add("generate-source", cmd_generate_source,
            "write a source spec from bronze metadata", target=True)
    p.add_argument("source")
    p.add_argument("--schema", help="bronze schema (default: the source name)")
    p = add("deploy", cmd_deploy, "publish notebooks and gold T-SQL",
            target=True)
    p.add_argument("--sql-only", action="store_true")
    p.add_argument("--notebooks-only", action="store_true")
    p.add_argument("--ai", action="store_true",
                   help="also publish the semantic model and Data Agents")
    p.add_argument("--ai-only", action="store_true",
                   help="publish only the semantic model and Data Agents "
                        "(after the gold tables are loaded)")
    p = add("run-silver", cmd_run_silver, "run the silver layer", target=True)
    p.add_argument("--load-date")
    p.add_argument("--full-refresh", action="store_true")
    p = add("test", cmd_test, "run data quality tests", target=True)
    p.add_argument("--layer", default="all",
                   choices=["all", "source", "silver", "gold"])
    p.add_argument("--select", help="only tables whose name contains this")
    p = add("test-agent", cmd_test_agent,
            "run Data Agent example questions", target=True)
    p.add_argument("--select", help="only agents whose name contains this")
    p = add("build", cmd_build, "deploy, run and test", target=True)
    p.add_argument("--layer", default="all", choices=["all", "silver", "gold"])
    p.add_argument("--load-date")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--skip-source-tests", action="store_true")

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except connect.TargetError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
