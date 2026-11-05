# Copilot instructions

This is a Microsoft Fabric data engineering project **without dbt**. You write table specs (`models/**/*.yml`) and SELECTs (`models/**/*.sql`). The `fde` toolkit (`python -m fde`) renders and deploys the code, then runs and tests it:

- silver: PySpark notebooks (`fabric/`)
- gold: T-SQL tables, views and stored procedures (`gold/`)

Calybre DE Standards Policy v2 applies in full.

Full rules: `AGENTS.md` (root) and `fabric_engineering_standards.md`. Folder-specific rules are in `.github/instructions/`.

## Layer flow

bronze (`models/sources/`) → silver source tables (`models/silver/<source>/`, spec only) → silver integrated tables (`models/silver/<domain>/`, Spark SQL) → gold `Dim`/`Fact`/`Bridge` (`models/gold/<domain>/`, T-SQL) → Power BI

- Never edit `fabric/nb_*` or `gold/**`. Change the spec or SELECT and run `python -m fde render`.
- Read tables only with `{{ ref('schema.Table') }}`. Never hard-code `lh_bronze.`, `lh_silver.` or `wh_gold.`.
- Silver never reads gold. Silver source tables never join or aggregate.
- Never write notebooks, stored procedures, MERGE, DDL or GRANT by hand.

## AI enablement

- The semantic model (`fabric/sm_*.SemanticModel/`) and Data Agents (`fabric/da_*.DataAgent/`) are rendered from the gold specs and `models/agents/<Name>.yml`. Never edit them by hand.
- Describe every column and measure. Measures are plain aggregates or carry `dax:`. `synonyms` and `ai_instructions` are only written when a person gave them.
- PII never reaches an AI item: no PII tables in an agent's warehouse source. See `.github/instructions/ai.instructions.md`.

## Naming

- Tables are PascalCase and singular. Gold tables start with `Dim`, `Fact` or `Bridge`.
- Columns are PascalCase:
  - business keys `<Entity>_BK` (with `business_key: true`)
  - booleans `Is`/`Has`
  - `...Date` is a date, `...Timestamp` is a UTC timestamp
  - money `...Amount`, `decimal(18,2)`
  - no abbreviations
- The kit adds `_SK`, `StartDate`/`EndDate`/`IsCurrent` and the audit columns. Never declare them.

## Every table

- The description states `Grain = ...`. Every column is described (meaning, unit, allowed values).
- Business tests (`accepted_values`, `accepted_range`, `expression`, `reconciles_to`). Key tests are implied.
- PII columns carry `meta.pii: true` in every layer. Never print PII values.
- No `getdate()`, `newid()`, `rand()` or `current_timestamp` in logic. Dates come from `load_date` / `@LoadDate`.

## Before you finish

Run `python -m fde render`; `python -m fde check` must pass. End with the "How to finish every task" block in `AGENTS.md`.

## Code review

Flag issues in this order:

1. Hand edits to rendered files
2. Layer violations
3. Missing keys, tests or descriptions
4. Naming and type violations
5. Non-deterministic logic
6. Style

Cite the rule id (`fabric_engineering_standards.md`, section 12).
