---
applyTo: "models/agents/**,models/gold/**,fde.yml"
---

# AI enablement (semantic model and Data Agents)

The kit renders two AI-facing Fabric items from the specs. You never write them by hand.

| Item | Spec | Rendered to |
| --- | --- | --- |
| Power BI semantic model (Direct Lake on `wh_gold`) | gold `.yml`: columns, `references:`, `measures:`, `synonyms:`, `ai_instructions:` | `fabric/<sm>.SemanticModel/` (TMDL) |
| Fabric Data Agent | `models/agents/<Name>.yml` | `fabric/da_<name>.DataAgent/` (draft stage) |

The semantic model is the Fabric counterpart of a Databricks metric view. Its measures and descriptions are what Copilot and Data Agents read, so they decide how good the answers are.

## Gold spec keys read by the AI items

```yaml
description: One row per issued new business policy. Grain = Policy_BK.
synonyms: [New business, Sales]            # other names the business uses
ai_instructions: Use for how many policies were sold. A policy counts once,
  on its issue date.                       # guidance for AI items, plain words
columns:
  - name: AnnualPremiumAmount
    description: Annualised premium in policy currency.
    synonyms: [Premium]
measures:
  - name: AnnualPremiumTotal
    expression: sum(AnnualPremiumAmount)   # plain sum/avg/min/max/count only
    description: Total annualised premium of new business.
    synonyms: [Total premium]
    format: "#,0.00"                       # optional DAX format string
  - name: PremiumPerPolicy
    expression: sum(AnnualPremiumAmount) / count(Policy_BK)
    dax: DIVIDE([AnnualPremiumTotal], [NewBusinessCount])   # not a plain aggregate
    description: Average annualised premium per policy.
```

- A measure `expression` that is not a plain aggregate over one column of the fact needs `dax:` (rule A1). Never leave it for someone to fix in Power BI: the semantic model is rendered, and a hand edit is reported as drift (R1).
- Write the description the way you would explain it to a new colleague: meaning, unit, allowed values. Descriptions and synonyms are the AI's only knowledge of your data.
- Synonyms are words people actually use. Don't invent them: ask, or leave them out.

## Personal data

- `ai.pii: exclude` in `fde.yml` is the default. Columns marked `meta.pii: true` are left out of the semantic model, so no AI item can read them.
- A Data Agent can select tables, not columns. A warehouse source must never list a table with PII columns (rule A5). Give people-level questions to the semantic model source, or split the PII into its own table.
- Never put PII values in `instructions`, `ai_instructions` or example queries.

## Data agent spec (`models/agents/<Name>.yml`)

```yaml
description: Answers new business sales questions for the distribution team.
instructions: |
  What the agent is for, what it must never do, how to word answers.
sources:
  - semantic_model: true            # totals, counts, trends
    instructions: Prefer the measures over summing columns yourself.
  - warehouse: true                 # row-level detail
    tables: [sales.FactNewBusiness]
    instructions: Use when the measures cannot answer.
examples:                           # question -> T-SQL, 3 or more
  - question: How many policies were issued per product?
    query: |
      select FactNewBusiness.ProductCode,
          count(FactNewBusiness.Policy_BK) as PolicyCount
      from {{ ref('sales.FactNewBusiness') }} as FactNewBusiness
      group by FactNewBusiness.ProductCode
    expect_columns: [ProductCode, PolicyCount]
```

- The file name is the agent name (PascalCase). The item is `da_<snake_name>`.
- Example queries are T-SQL SELECTs over `{{ ref() }}` of the tables the warehouse source selects. Only the warehouse source supports examples.
- Cover the questions people ask most, in the words they use. Run them: `python -m fde test-agent --target dev`. An example passes when it runs and returns rows (`allow_empty: true` accepts none).
- Only the draft stage is rendered. A person publishes the agent in Fabric.
- Instructions: say what the agent is for, what it must not do (no guessing numbers, no personal data), the unit and currency, and to state the date range of every answer.

## Unstructured data and AI functions (pattern, not rendered yet)

The kit does not render notebooks that call Fabric AI functions. If a project needs them (for example classifying call transcripts), the rules are:

- Land the text in silver as its own table. Chunk at natural boundaries (turns, paragraphs). Every chunk keeps its source row key (`<Entity>_BK`).
- Every AI-derived column carries its provenance: the source key, the prompt name and version (for example `signal_classify_v3`) and the model or endpoint, recorded in the table `meta`.
- Prompts live in the repo (`prompts/`) with a version name.
- The AI function runs only in an incremental silver load, so each row is scored once. Never in a view and never in gold.
- Output matches a declared schema: `accepted_values` on every label, and a test that generated text is grounded in its source.
- Stop and tell the user that this needs a toolkit change (a new silver table kind in `fde/render.py`). Do not hand-write the notebook.
