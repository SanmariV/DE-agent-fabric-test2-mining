# Fabric Data Engineering Agent Kit

A starter kit for using GitHub Copilot to scaffold and build silver and gold layers in **Microsoft Fabric without dbt**. It is the Fabric counterpart of the Databricks dbt agent kit. The agent workflow, the prompts and the quality bar are the same. The engine is different: a small Python toolkit, `fde`, and native Fabric items. `fde` stands for **Fabric Data Engineering**; you run it as `python -m fde`, much as you would run `dbt`.

**New here? Read [`START_HERE.md`](START_HERE.md).** It walks you through setup and every prompt, step by step.

## How it works

```
models/  (you and the agent write these)            fde render          Fabric runs these
  sources/<source>.yml        bronze tables       ──────────────►   (generated, committed, never hand-edited)
  silver/<source>/<T>.yml     1:1 bronze cleanup                      fabric/nb_silver_*      PySpark + Delta MERGE
  silver/<domain>/<T>.yml+sql joins, business rules                   fabric/nb_ops_run_silver
  gold/<domain>/<T>.yml+sql   Dim / Fact / Bridge                     gold/**                 T-SQL table, view,
                                                                                              Load<T> procedure,
                                                                                              ops tests + loads
```

- **Silver** runs on a Lakehouse (`lh_silver`). Each table gets one rendered PySpark notebook that reads, casts, deduplicates and MERGEs, with the DE Policy v2 audit columns.
- **Gold** runs on a Warehouse (`wh_gold`). Each table gets one rendered `Load<Table>` stored procedure (MERGE, with SCD2 for type 2 dimensions), `_SK` keys and an unknown member row.
- **Tests:**
  - implied tests on every table: keys, uniqueness, SCD2 integrity, relationships
  - tests declared in the spec: accepted values, ranges, expressions, reconciliations
  The same SQL runs from your laptop (`fde test`) and in the pipeline (`ops.RunDataQualityTests`), which stops the load when an error-severity test fails.
- **Orchestration** is a fixed five-activity Fabric pipeline. Adding tables never changes it.
- **Calybre DE Standards Policy v2 is met directly.** The kit renders notebooks in silver and one stored procedure per gold table. No TEC exceptions are needed (the Databricks kit needs them for dbt).

## What's included

| Path | What it is |
| --- | --- |
| [`AGENTS.md`](AGENTS.md), [`.github/copilot-instructions.md`](.github/copilot-instructions.md), [`.github/instructions/`](.github/instructions/) | Rules Copilot follows |
| [`.github/prompts/`](.github/prompts/) | `/scaffold-fabric-project`, `/build-intermediate`, `/build-marts`, `/project-check`, `/build-ai-layer`, `/information-matrix`, `/data-architecture-diagram` |
| [`fabric_engineering_standards.md`](fabric_engineering_standards.md) | The standard: architecture, layer rules, rendered code, tests, deployment, check rules, Policy v2 mapping, spike list |
| [`fde/`](fde/) | The toolkit: `python -m fde parse / check / render / generate-source / show / deploy / build / test / test-agent` |
| [`fde/semantic.py`](fde/semantic.py), [`fde/agent.py`](fde/agent.py) | AI enablement: render the Direct Lake semantic model (TMDL) and Fabric Data Agents from the specs |
| [`common/fabric_de_common/`](common/fabric_de_common/) | Shared notebook library, installed in the Fabric Environment as a wheel |
| [`scripts/build_information_matrix.py`](scripts/build_information_matrix.py) | Information Matrix workbook from `target/manifest.json` |
| [`examples/insurance/`](examples/insurance/) | A complete worked example: specs, SELECTs and the rendered notebooks and T-SQL |
| [`tests/`](tests/) | Offline tests for the toolkit (rendered T-SQL is parsed, notebooks compiled, rules exercised) |

## Getting started

```powershell
pip install -r requirements.txt
python -m pytest -q                       # offline; should pass
python -m fde check                       # on this (empty) project
cd examples/insurance; python -m fde check; python -m fde ls --tests
```

Then follow `START_HERE.md`: create the Fabric items, set `FABRIC_DEV_SQL_ENDPOINT` and `FABRIC_DEV_WORKSPACE_ID`, install the shared library, and run `/scaffold-fabric-project` in Copilot Chat (Agent mode).

## Project conventions

- Edit `models/` only. `fabric/nb_*` and `gold/` are rendered by `python -m fde render`, and `python -m fde check` fails on hand edits.
- Use the `dev` target locally. `test` and `prod` are protected and written only by the release pipeline.
- Never commit hosts, ids, tokens or the Information Matrix workbook (it holds sampled data).
- Items marked **[Spike]** in the standard must be confirmed on a real capacity before production (section 15).
