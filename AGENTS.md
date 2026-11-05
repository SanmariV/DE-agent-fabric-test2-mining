# AGENTS.md

Instructions for GitHub Copilot (Chat, agent mode, code review and the coding agent) working in this repository.
The full rationale lives in `fabric_engineering_standards.md`. These rules win over your general habits. If a request conflicts with a rule, say so instead of breaking it silently.

## What this repo is

A Microsoft Fabric data engineering project **without dbt**. You write table **specs** (YAML) and **SELECTs**. The `fde` toolkit renders the code Fabric runs, deploys it, runs it and tests it.

- Silver: a Lakehouse (`lh_silver`, schemas enabled), loaded by PySpark notebooks with Delta MERGE.
- Gold: a Fabric Data Warehouse (`wh_gold`), loaded by one T-SQL stored procedure per table with MERGE.
- Bronze (`lh_bronze`) is loaded by Fabric pipelines, not by this repo. This repo only reads it.
- Calybre DE Standards Policy v2 applies in full: `_BK` / `_SK` keys, the four audit columns, `StartDate` / `EndDate` / `IsCurrent`, notebooks in silver and stored procedures in gold.

```
bronze (models/sources) → silver source tables → silver integrated tables → gold Dim/Fact/Bridge → Power BI
```

## What you edit, and what you never edit

| You write | Never edit by hand (rendered by `python -m fde render`) |
| --- | --- |
| `models/sources/<source>.yml` (start it with `fde generate-source`) | `fabric/nb_*.Notebook/**` |
| `models/silver/<schema>/<Table>.yml` (+ `.sql` for integrated tables) | `fabric/parameter.yml` |
| `models/gold/<domain>/<Table>.yml` + `.sql` | `gold/**` (tables, views, procedures, ops) |
| `models/agents/<Name>.yml` (Data Agents) | `fabric/sm_*.SemanticModel/**`, `fabric/da_*.DataAgent/**` |
| `reference/business_glossary.csv`, `fde.yml` | |

After any change under `models/`, run `python -m fde render` and commit the rendered files with the spec. `python -m fde check` fails on hand edits and stale files (rule R1).

Do not write notebooks, stored procedures, `MERGE`, `CREATE TABLE` or `GRANT` statements yourself. Express the change in the spec or the SELECT. If something cannot be expressed that way, stop and say so. Do not work around it.

## Layer rules (never break these)

| Layer | Folder | Reads | Built as |
| --- | --- | --- | --- |
| Silver source table | `models/silver/<source>/` | exactly one bronze table, named in the spec's `source:` | Spec only: an `expression` per column (Spark SQL over bronze columns) |
| Silver integrated table | `models/silver/<domain>/` | silver tables via `{{ ref('schema.Table') }}` | Spec + Spark SQL SELECT |
| Gold table | `models/gold/<domain>/` | silver and gold tables via `{{ ref() }}` | Spec + T-SQL SELECT |

- One silver source table per bronze table (1:1). Source tables rename, cast, trim, upper-case codes, handle nulls and set `Is`/`Has` flags. They never join, aggregate or apply business rules.
- Joins, business rules and re-graining go in integrated silver tables (the "intermediate" layer) or in the gold SELECT.
- Silver never reads gold. A dimension reading a fact is a design smell.
- Never hard-code `lh_bronze.`, `lh_silver.` or `wh_gold.` names. Use `{{ ref('schema.Table') }}`.
- The schema of a table is its folder. The table name is its file name.

## Specs

```yaml
# models/gold/distribution/DimAgent.yml
description: One row per agent version (SCD type 2). Grain = Agent_BK, StartDate.
scd_type: 2                      # dimensions only: 1 or 2
columns:
  - name: Agent_BK
    data_type: varchar(20)       # Fabric Warehouse type in gold, Spark type in silver
    business_key: true
    description: Agent code from the policy admin system.
  - name: AgentName
    data_type: varchar(200)
    description: Agent full name.
    meta: {pii: true, matrix: {example: "Thabo M***"}}
```

- Every table: a description with `Grain = ...`, at least one `business_key: true` column, and a description on every column (meaning, unit, allowed values).
- Never declare the columns the kit adds: `<Table>_SK`, `StartDate`, `EndDate`, `IsCurrent` and the four audit columns.
- Facts point to dimensions with `<Role><DimTable>_SK bigint` + `references: <domain>.<DimTable>`. The SELECT resolves the key with a point-in-time join and `coalesce(..., -1)`.
- Large facts: `load: {mode: incremental, column: <date column>, lookback_days: <n>}`.
- Measures go on facts (`measures:` with `name`, `expression`, `description`). They document the Power BI semantic model.

## Naming

| Thing | Pattern | Example |
| --- | --- | --- |
| Schema (folder) | snake_case: source name, or domain | `policy_admin`, `sales` |
| Silver table | PascalCase singular, no prefix | `Policy`, `NewBusinessPolicy` |
| Gold table | `Dim` / `Fact` / `Bridge` + PascalCase | `DimAgent`, `FactNewBusiness` |
| Business key | `<Entity>_BK` | `Policy_BK` |
| Boolean | `Is` / `Has` | `IsActive` |
| Date / timestamp | `...Date` (date), `...Timestamp` (UTC) | `IssueDate` |
| Money | `...Amount`, `decimal(18,2)` | `AnnualPremiumAmount` |
| Code | `...Code`, upper-cased | `PolicyStatusCode` |

No abbreviations (`Amount`, not `Amt`; `Number`, not `No`). Gold types: `varchar(n)`, `decimal(p,s)`, `bit`, `date`, `datetime2(6)`, `int`, `bigint`. Never `nvarchar`, `datetime`, `money` or `tinyint`: the Fabric Warehouse rejects them.

## SQL style (the `.sql` files)

- Lowercase keywords, 4-space indents, trailing commas, lines of 80 characters or fewer.
- Import CTEs first (one per `ref`), then one-job CTEs, then a final `select`.
- Explicit `as`. `inner join` / `left join` only. No single-letter aliases. Prefix columns with the CTE name when joining.
- Gold SELECTs are T-SQL views: no `@parameters`, no `order by`, no `limit`, no `group by 1` or `group by all`.
- Silver integrated SELECTs are Spark SQL and MAY use `:load_date`.
- Never use `getdate()`, `sysdatetime()`, `current_timestamp`, `newid()` or `rand()` in logic. Dates come from `load_date` / `@LoadDate`.

## Tests

The kit adds key, uniqueness, SCD2 and relationship tests to every table (`fabric_engineering_standards.md`, section 8.1). You add the business ones:

- `accepted_values` on every code column whose allowed values are known
- `accepted_range` on amounts, ages and rates
- `expression` for row rules (`IssueDate >= ApplicationDate`)
- `reconciles_to` a control total on every financial fact
- `row_count_between` / `recency` on key facts

Never delete or weaken a failing test to make a build pass. A failing test is a data quality finding: report it.

## Commands

```bash
python -m fde parse                    # specs load; writes target/manifest.json
python -m fde check                    # all rules + render drift (run before every commit)
python -m fde render                   # regenerate notebooks and T-SQL
python -m fde ls --tests               # list tables and tests
python -m fde debug --target dev       # connection check
python -m fde generate-source <source> # bronze metadata -> models/sources/<source>.yml
python -m fde show "select ..."        # one read-only query; {{ ref() }} allowed
python -m fde build --target dev       # deploy, run silver, load gold, test
python -m fde build --target dev --layer gold --skip-deploy
python -m fde deploy --target dev --ai-only      # semantic model + Data Agents
python -m fde test-agent --target dev            # run the agent example questions
python -m fde test --target dev --layer silver --select Policy
```

Use `--target dev` only. `test` and `prod` are protected; only the release pipeline writes to them. Never put hosts, ids, tokens or secrets in any file.

## Check the data before you ask the user

Before you put a question to the user, ask whether the data can answer it. Run a read-only query and report the evidence. Ask the user only what the data can't answer: what a code means, units and business rules.

- **Grain and keys:** is this combination unique? Compare `count(*)` with `count(distinct ...)`.
- **Join coverage:** how many rows have no match, and why (null key, or a key missing from the other table)?
- **Constant or changing:** is an attribute the same across the grain you plan to aggregate to?
- **Null rates and ranges:** how many nulls, and what are the min and max?

How:

- `python -m fde show "<select ...>" --target dev`. Reference tables with `{{ ref('schema.Table') }}`, or bronze with `{{ source('<source>', '<table>') }}`. The query runs on the Warehouse in T-SQL.
- Put several checks into one query with `union all`. Return counts and aggregates, never row-level data. Never print values from PII columns.
- State the result in the question, e.g. "Answered from data: channel never varies within a policy (0 of 106,433). Recommend: include it."
- A query result tells you what the data does, not what it means. Don't invent a business rule from it.

## Personal data (PII)

Whenever you create or change a table, check every column for personal data and mark it. Don't wait to be asked.

- `meta.pii: true` for names, emails, phone numbers, addresses, postal codes, dates of birth, exact age, gender, ID numbers and anything derived from them. Mark the column in every layer it appears in.
- Health, claims and person-level financial amounts are sensitive. Don't mark them automatically. List them under "Decisions for you" with a recommendation.
- Never sample or print PII values. A PII `meta.matrix.example` must be synthetic (`Thabo M***`).
- In your summary, list the columns you marked.

## Planning and building silver integrated and gold tables

When asked to build "intermediate"/integrated silver tables (`/build-intermediate`) or gold tables (`/build-marts`), work in two phases with a stop between them:

1. **Propose, don't build.** Read the existing specs, check the data, then propose tables (name, grain, inputs, what it does) with open questions and a recommended answer for each.
2. **Build only what the user confirms.** Rules and join keys the data doesn't settle become `TODO(...)` in the spec description and are listed.

## AI enablement (semantic model and Data Agents)

The kit renders a Direct Lake **semantic model** (the Fabric counterpart of a Databricks metric view) from the gold specs, and a **Data Agent** from `models/agents/<Name>.yml`. Follow `.github/instructions/ai.instructions.md`, and `.github/prompts/build-ai-layer.prompt.md` for the plan-then-build flow (`/build-ai-layer`).

- Never edit `fabric/sm_*.SemanticModel/**` or `fabric/da_*.DataAgent/**`. Change the spec and run `python -m fde render` (rule R1).
- Every column and measure has a business description (meaning, unit, allowed values). Every fact has at least one measure. A measure is a plain `sum`/`avg`/`min`/`max`/`count` over one column, or you write `dax:` (rules A1, A7).
- `synonyms:` (table, column, measure) and `ai_instructions:` (table) are facts people know. Never invent them. Leave them out and list them under "Decisions for you".
- PII columns stay out of the semantic model (`ai.pii: exclude` in `fde.yml`). A Data Agent cannot hide single columns, so a warehouse source never lists a table with PII columns (rule A5). Never put PII values in instructions or examples.
- An agent has a description, instructions, at least one source, and three or more example questions as T-SQL over `{{ ref() }}` of tables its warehouse source selects (rules A3, A4, A6). Only the warehouse source supports examples.
- Run the examples: `python -m fde test-agent --target dev`. A failing example is a finding: report it, don't delete or weaken it.
- Publish after gold is loaded: `python -m fde deploy --target dev --ai-only`. A person publishes each Data Agent in Fabric.
- AI functions (Fabric AI functions over text) are not rendered by the kit yet. If asked, apply the rules in `ai.instructions.md` (provenance, versioned prompts, incremental only) and tell the user it needs a toolkit change. Never hand-write the notebook.

## Scaffolding a project

New projects and new sources are scaffolded with `.github/prompts/scaffold-fabric-project.prompt.md`. Never invent ids, hosts, keys or column meanings. Write `TODO(...)` and report it.

## Information Matrix

The client Information Matrix (`.xlsx`) is generated by `scripts/build_information_matrix.py` from `target/manifest.json`. Follow `.github/prompts/information-matrix.prompt.md`.

- NEVER edit the workbook by hand, and never commit it (it holds sampled data). It is written to `target/`.
- Facts only people know go in `meta.matrix` on the table or column (keys in `.github/instructions/gold.instructions.md`). If you don't know a value, leave it out; the gap report lists it. Never guess.
- BUS Matrix rows come from `references` columns. Measures come from `measures:` on facts.
- When silver and gold build and their tests pass, finish by generating the matrix. Don't wait to be asked.

## How to finish every task (what the user sees)

End **every** task with this block, and nothing after it. Keep earlier chat short: one line per step.

```
<Task> finished. Details: <file, if you wrote a report>

Result: <n> tables, <n> tests (<n> pass), <n> TODOs.
Checks: fde check <pass/fail> | fde render <up to date/changed> | fde build <pass/fail/not run>

Decisions for you:
1. <question>. Recommend: <your answer>.
(only things the data couldn't answer; leave this block out if there are none)

Your next steps:
1. <the single most important action, with the exact command or file>
2. ...
(at most 5, in order)

Reply "<short phrase>" and I will <what happens next>.
```

- "Your next steps" is always present, numbered, and starts with a blocking item if there is one.
- Each decision has a recommended answer. If a check failed, step 1 is how to fix it.

## Before you finish a change

- [ ] Right folder, file name and prefix; `ref()` only, no hard-coded names
- [ ] Grain in the description; every column described; business key marked
- [ ] Business tests added; PII marked in every layer
- [ ] Measures described (and `synonyms` only where known); agent examples run with `test-agent`
- [ ] `python -m fde render` run and rendered files included
- [ ] `python -m fde check` passes
- [ ] `python -m fde build --target dev` passes for the changed layer (when a dev workspace is available)
- [ ] One story per pull request

## When reviewing pull requests

Flag issues in this order, citing the rule id from `fabric_engineering_standards.md`, section 12:

1. Hand edits to rendered files (R1)
2. Layer violations (L*)
3. Missing keys, tests or descriptions (S*, T*)
4. Naming and type violations (N*, D*)
5. Non-deterministic logic (I1)
6. Style
