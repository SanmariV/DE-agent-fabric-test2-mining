"""Tests for the fde toolkit and the shared notebook library.

They run offline: no Fabric workspace is needed. The worked example in
``examples/insurance`` is the main fixture.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import sqlglot

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "insurance"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "common"))

from fabric_de_common import silver  # noqa: E402
from fde import check, connect, dq, manifest, render  # noqa: E402
from fde.project import load_project  # noqa: E402


@pytest.fixture()
def example():
    """Return the loaded example project."""
    return load_project(EXAMPLE)


@pytest.fixture()
def scratch(tmp_path):
    """Return a writable copy of the example project."""
    target = tmp_path / "project"
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns("target"))
    return target


def _batches(text: str):
    """Yield the non-empty GO-separated batches of a script."""
    for batch in re.split(r"^\s*GO\s*$", text, flags=re.M):
        if re.sub(r"--[^\n]*", "", batch).strip():
            yield batch


def _code_cells(text: str) -> str:
    """Return the parameters and code cells of a Fabric notebook."""
    cells = re.split(r"^# (?:PARAMETERS )?CELL \*+\s*$", text, flags=re.M)[1:]
    return "\n".join(c.split("# METADATA ****")[0] for c in cells)


def test_example_has_no_findings(example):
    findings = check.run_checks(example)
    assert [f for f in findings if f.severity == "error"] == []


def test_example_render_is_committed_and_current(example):
    assert render.write(example, check=True) == []


def test_render_is_deterministic(example):
    assert render.render_all(example) == render.render_all(example)


def test_notebooks_are_valid_python(example):
    for path, content in render.render_all(example).items():
        if path.endswith("notebook-content.py"):
            code = _code_cells(content)
            compile(code, path, "exec")
            assert "def main(" in code
            assert content.count("# MARKDOWN") >= 3, path


def test_gold_sql_parses(example):
    for path, content in render.render_all(example).items():
        if not path.endswith(".sql"):
            continue
        for batch in _batches(content):
            if "PRIMARY KEY NONCLUSTERED" in batch:
                continue  # Fabric NOT ENFORCED syntax; sqlglot lacks it
            batch = re.sub(r"THROW [^;]+;", "RETURN;", batch)
            sqlglot.parse(batch, read="tsql",
                          error_level=sqlglot.ErrorLevel.RAISE)


def test_every_test_query_parses(example):
    tests = dq.all_tests(example)
    assert {t.layer for t in tests} == {"source", "silver", "gold"}
    for test in tests:
        sqlglot.parse_one(dq.count_sql(example, test), read="tsql")


def test_implied_tests(example):
    names = {(t.table, t.name) for t in dq.all_tests(example)}
    assert ("distribution.DimAgent", "one_current_row__Agent_BK") in names
    assert ("distribution.DimAgent",
            "no_overlapping_versions__Agent_BK") in names
    assert ("sales.FactNewBusiness", "relationships__DimAgent_SK") in names
    assert ("policy_admin.Policy", "unique__Policy_BK") in names


def test_scd2_procedure_closes_and_inserts(example):
    sql = render.gold_procedure_sql(example,
                                    example.models["distribution.DimAgent"])
    assert "[EndDate] = DATEADD(day, -1, @LoadDate)" in sql
    assert "NULL AS [MergeKey1]" in sql
    assert " OR OR " not in sql


def test_load_order_puts_dimensions_first(example):
    order = [m.key for m in example.load_order(example.gold())]
    assert order.index("distribution.DimAgent") < order.index(
        "sales.FactNewBusiness")


def test_refs_resolve_per_engine(example):
    sql = "select * from {{ ref('policy_admin.Policy') }}"
    # T-SQL names of silver tables are lower-case: the Warehouse is
    # case-sensitive and Spark stores Lakehouse tables in lower case.
    assert "[lh_silver].[policy_admin].[policy]" in example.resolve_sql(
        sql, "tsql")
    assert "lh_silver.policy_admin.Policy" in example.resolve_sql(sql, "spark")


def test_manifest_shape(example):
    built = manifest.build(example)
    names = {n["name"] for n in built["nodes"].values()
             if n["resource_type"] == "model"}
    assert {"stg_policy_admin__policy", "int_sales__new_business_policy",
            "dim_agent", "fct_new_business", "mv_new_business"} <= names
    rel_tests = [n for n in built["nodes"].values()
                 if n["resource_type"] == "test"
                 and n["test_metadata"]["name"] == "relationships"]
    assert len(rel_tests[0]["depends_on"]["nodes"]) == 2
    assert any(e["source_column"] == "policy_no"
               for e in built["lineage"])


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_checks_catch_violations(scratch):
    gold = scratch / "models" / "gold" / "sales"
    _write(gold / "FactBad.yml", """
description: Bad fact without a grain.
columns:
  - name: Policy_BK
    data_type: nvarchar(20)
    business_key: true
    description: Key.
  - name: PremAmt
    data_type: float
    description: Money as float.
  - name: Active
    data_type: bit
    description: Flag without Is.
  - name: AgentKey_SK
    data_type: bigint
    description: Missing references.
""")
    _write(gold / "FactBad.sql", "select * from lh_silver.policy_admin.Policy "
           "where IssueDate < getdate()")
    rules = {f.rule for f in check.run_checks(load_project(scratch))
             if f.severity == "error"}
    assert {"S2", "D2", "D3", "N9", "G2", "L5", "I1"} <= rules


def test_checks_catch_layer_breaks(scratch):
    silver_dir = scratch / "models" / "silver" / "sales"
    _write(silver_dir / "ReadsGold.yml", """
description: Reads gold. Grain = Policy_BK.
columns:
  - {name: Policy_BK, data_type: string, business_key: true, description: Key.}
""")
    _write(silver_dir / "ReadsGold.sql",
           "select Policy_BK from {{ ref('sales.FactNewBusiness') }}")
    rules = {f.rule for f in check.run_checks(load_project(scratch))}
    assert "L3" in rules


def test_render_check_detects_hand_edits(scratch):
    target = scratch / "gold" / "sales" / "procedures" / \
        "LoadFactNewBusiness.sql"
    target.write_text(target.read_text() + "-- edited\n")
    messages = render.write(load_project(scratch), check=True)
    assert any("LoadFactNewBusiness" in m for m in messages)


def test_render_removes_stale_files(scratch):
    (scratch / "models" / "gold" / "sales" / "FactNewBusiness.yml").unlink()
    (scratch / "models" / "gold" / "sales" / "FactNewBusiness.sql").unlink()
    messages = render.write(load_project(scratch))
    assert any(m.startswith("removed: gold/sales/") for m in messages)


def test_read_only_guard():
    connect.assert_read_only("select LastUpdateTimestamp from x")
    connect.assert_read_only("with a as (select 1 as n) select n from a")
    connect.assert_read_only("select 'it''s; -- /*' as a, [x;y] from t -- c")
    for bad in ["delete from x", "select 1; drop table x",
                "select * into y from x", "exec sp_who",
                "select '/*' ; delete from t; select '*/'",
                "select 1 /* x */ ; drop table t",
                "select '--' as a; drop table t",
                "select [a]; drop table t", "select 'open",
                "select 1 -- x\rdelete from t", "select 1 commit",
                "select 1 waitfor delay '0:0:5'"]:
        with pytest.raises(connect.TargetError):
            connect.assert_read_only(bad)


def test_silver_helpers():
    assert silver.resolve_load_date("2026-10-31") == "2026-10-31"
    import datetime as dt
    assert silver.resolve_load_date("", dt.date(2026, 11, 4)) == "2026-11-03"
    exprs = silver.select_expressions(
        [("Customer_BK", "string", "upper(id)")], ["_ingested_at desc"])
    assert exprs == ["cast((upper(id)) as string) as `Customer_BK`",
                     "_ingested_at as `__order_0_desc`"]
    assert silver.change_condition(["A", "B"]) == \
        "not (t.`A` <=> s.`A`) or not (t.`B` <=> s.`B`)"
    assert silver.change_condition([]) is None
    ddl = silver.table_ddl("lh.s.T", [("Name", "string", "n"),
                                      ("T_BK", "string", "k")],
                           ["T_BK"], "It's a table")
    assert ddl.index("`T_BK` string NOT NULL") < ddl.index("`Name` string")
    assert "`LastUpdateTimestamp` timestamp NOT NULL" in ddl
    assert "It\\'s" in ddl


def test_cli_check_runs_in_example():
    result = subprocess.run([sys.executable, "-m", "fde", "check"],
                            cwd=EXAMPLE, capture_output=True, text=True,
                            env={"PYTHONPATH": str(ROOT),
                                 "SYSTEMROOT": "C:\\Windows",
                                 "PATH": ""})
    assert result.returncode == 0, result.stdout + result.stderr
