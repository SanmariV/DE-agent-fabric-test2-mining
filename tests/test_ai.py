"""Tests for AI enablement: the semantic model and the Data Agents.

They run offline against ``examples/insurance`` (no Fabric workspace).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import sqlglot

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "insurance"
sys.path.insert(0, str(ROOT))

from fde import agent, check, connect, render, semantic  # noqa: E402
from fde.project import load_project  # noqa: E402

SM = "fabric/sm_insurance_example.SemanticModel"
DA = "fabric/da_sales_analyst.DataAgent"
CONFIG = f"{DA}/Files/Config"


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


def _edit(path: Path, old: str, new: str) -> None:
    """Replace text in a spec, failing loudly when it is not there."""
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _errors(project) -> set:
    """Return the rule ids of every error finding."""
    return {f.rule for f in check.run_checks(project)
            if f.severity == "error"}


def test_measure_dax_translation(example):
    fact = example.models["sales.FactNewBusiness"]

    def dax(expression, **extra):
        return semantic.measure_dax(fact, {"expression": expression, **extra})

    assert dax("sum(AnnualPremiumAmount)") == \
        "SUM('FactNewBusiness'[AnnualPremiumAmount])"
    assert dax("COUNT( Policy_BK )") == "COUNT('FactNewBusiness'[Policy_BK])"
    assert dax("count(distinct Policy_BK)") == \
        "DISTINCTCOUNT('FactNewBusiness'[Policy_BK])"
    assert dax("count(*)") == "COUNTROWS('FactNewBusiness')"
    assert dax("avg(AnnualPremiumAmount)").startswith("AVERAGE(")
    assert dax("sum(NoSuchColumn)") is None
    assert dax("sum(distinct AnnualPremiumAmount)") is None
    assert dax("sum(AnnualPremiumAmount) / count(Policy_BK)") is None
    assert dax("anything", dax="DIVIDE([A], [B])") == "DIVIDE([A], [B])"


def test_example_has_no_ai_errors_and_render_is_current(example):
    assert _errors(example) == set()
    assert render.write(example, check=True) == []


def test_semantic_model_is_rendered(example):
    files = render.render_all(example)
    fact = files[f"{SM}/definition/tables/FactNewBusiness.tmdl"]
    assert "measure NewBusinessCount = COUNT('FactNewBusiness'[Policy_BK])" \
        in fact
    assert "Also known as: Premium, Annual premium." in fact
    assert "Guidance: Use for how many policies" in fact
    assert "mode: directLake" in fact and "schemaName: sales" in fact
    assert "isHidden" in fact
    assert "fromColumn: FactNewBusiness.DimAgent_SK" in \
        files[f"{SM}/definition/relationships.tmdl"]
    assert "ref table DimAgent" in files[f"{SM}/definition/model.tmdl"]
    assert '"type": "SemanticModel"' in files[f"{SM}/.platform"]


def test_semantic_model_leaves_pii_out(example):
    dim = f"{SM}/definition/tables/DimAgent.tmdl"
    files = render.render_all(example)
    assert "AgentName" not in files[dim]
    assert "BranchCode" in files[dim]
    example.config.raw["ai"]["pii"] = "include"
    assert "AgentName" in render.render_all(example)[dim]


def test_tmdl_uses_tabs_and_unique_lineage_tags(example):
    tmdl = {p: t for p, t in render.render_all(example).items()
            if p.endswith(".tmdl")}
    assert tmdl
    for path, text in tmdl.items():
        for line in text.splitlines():
            if not path.endswith("expressions.tmdl"):
                assert not line.startswith(" "), (path, line)
    tags = re.findall(r"lineageTag: (\S+)", "\n".join(tmdl.values()))
    assert len(tags) == len(set(tags))


def test_inactive_relationship_for_a_second_role(example):
    fact = example.models["sales.FactNewBusiness"]
    fact.columns.append(type(fact.columns[1])(
        name="ReferralDimAgent_SK", data_type="bigint",
        description="Referring agent.", references="distribution.DimAgent"))
    active = [a for _, _, _, a in semantic.relationships(example)]
    assert active == [True, False]
    assert "isActive: false" in semantic.relationships_tmdl(example)


def test_agent_is_rendered(example):
    files = render.render_all(example)
    stage = json.loads(files[f"{CONFIG}/draft/stage_config.json"])
    assert "never guess a" in stage["aiInstructions"]
    assert "Table guidance." in stage["aiInstructions"]
    shots = json.loads(files[
        f"{CONFIG}/draft/warehouse-tables-wh_gold/fewshots.json"])["fewShots"]
    assert len(shots) == 3
    assert all("{{" not in s["query"] and "[sales].[FactNewBusiness]"
               in s["query"] for s in shots)
    assert len({s["id"] for s in shots}) == 3
    assert f"{CONFIG}/draft/semantic-model-sm_insurance_example/" \
        "datasource.json" in files
    assert not any(p.endswith("fewshots.json") and "semantic-model" in p
                   for p in files)
    assert json.loads(files[f"{CONFIG}/data_agent.json"])["$schema"]


def test_agent_never_sees_pii(example):
    files = render.render_all(example)
    for path, text in files.items():
        if path.startswith(DA):
            assert "AgentName" not in text, path
    warehouse = json.loads(files[
        f"{CONFIG}/draft/warehouse-tables-wh_gold/datasource.json"])
    tables = {t["display_name"]: t["is_selected"]
              for schema in warehouse["elements"]
              for t in schema["children"]}
    assert tables == {"DimAgent": False, "FactNewBusiness": True}


def test_agent_examples_parse_as_tsql(example):
    for item in example.agents.values():
        for shot in item.examples:
            sql = agent.example_sql(example, shot)
            sqlglot.parse_one(sql, read="tsql")
            connect.assert_read_only(sql)


def test_check_blocks_pii_table_in_warehouse_source(scratch):
    _edit(scratch / "models" / "agents" / "SalesAnalyst.yml",
          "tables: [sales.FactNewBusiness]",
          "tables: [sales.FactNewBusiness, distribution.DimAgent]")
    findings = check.run_checks(load_project(scratch))
    assert any(f.rule == "A5" and f.severity == "error"
               and "AgentName" in f.message for f in findings)


def test_check_catches_agent_problems(scratch):
    path = scratch / "models" / "agents" / "SalesAnalyst.yml"
    _edit(path, "instructions: |\n  You answer", "notes: |\n  You answer")
    _edit(path, "ref('sales.FactNewBusiness') }} as FactNewBusiness",
          "ref('sales.Nope') }} as FactNewBusiness")
    assert {"A3", "A4"} <= _errors(load_project(scratch))


def test_check_blocks_example_that_writes(scratch):
    _edit(scratch / "models" / "agents" / "SalesAnalyst.yml",
          "select\n          FactNewBusiness.ProductCode,\n"
          "          count(FactNewBusiness.Policy_BK) as PolicyCount",
          "delete from {{ ref('sales.FactNewBusiness') }}; select 1 as X")
    findings = check.run_checks(load_project(scratch))
    assert any(f.rule == "A4" and "only" in f.message.lower()
               for f in findings)


def test_check_catches_untranslatable_measure_and_bad_synonyms(scratch):
    path = scratch / "models" / "gold" / "sales" / "FactNewBusiness.yml"
    _edit(path, "expression: sum(AnnualPremiumAmount)",
          "expression: sum(AnnualPremiumAmount) / 2")
    _edit(path, "synonyms: [Product, Plan]", "synonyms: Product")
    assert {"A1", "A2"} <= _errors(load_project(scratch))


def test_removing_an_agent_removes_its_files(scratch):
    (scratch / "models" / "agents" / "SalesAnalyst.yml").unlink()
    messages = render.write(load_project(scratch))
    assert any(m.startswith("removed: fabric/da_sales_analyst")
               for m in messages)
    assert not list((scratch / "fabric").glob("da_*"))


def test_run_examples_reports_failures(example, monkeypatch):
    item = example.agents["SalesAnalyst"]

    def fake(connection, sql, limit=None):
        if "avg(" in sql:
            raise RuntimeError("boom")
        if "datefromparts" in sql:
            return []
        return [{"ProductCode": "A", "PolicyCount": 1}]

    monkeypatch.setattr(connect, "read_only_query", fake)
    results = agent.run_examples(example, item, connection=None)
    assert [r[1] for r in results] == [True, False, False]
    assert "no rows" in results[1][2] and "boom" in results[2][2]
