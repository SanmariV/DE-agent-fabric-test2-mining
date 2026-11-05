---
agent: agent
description: Make the gold layer AI-ready (semantic model and Data Agent). Propose first, build what the user confirms.
---

# Build the AI layer

Follow `AGENTS.md` and `.github/instructions/ai.instructions.md`. Synonyms, instructions and the meaning of a measure are facts people know: never invent them.

Gold must build and its tests must pass first. If not, say so and stop.

## Phase 1: Plan (change no files)

1. Read the gold specs, `fde.yml` and any `models/agents/*.yml`. Run `python -m fde render --check` to see what is already rendered.
2. For each fact, list the numeric columns that are not keys. A measure candidate is a sum or count of one of them; an average or ratio for rates. Never sum a rate or a balance. Check anything unclear with one read-only `python -m fde show` query (counts only, nothing from PII columns).
3. Check the AI readiness of every gold table:
   - a description on the table and every column, with unit and allowed values
   - at least one measure on each fact, each with a description
   - PII columns marked `meta.pii: true` (they stay out of the semantic model)
   - tables that mix PII with people-safe attributes: a Data Agent cannot hide a column
4. Print this, and nothing else:

```
AI layer planned

Semantic model (<sm name>): <n> tables, <n> relationships, <n> measures.
Left out because of PII: <columns, or none>.

Measures to add:
1. <Fact>.<MeasureName> = <expression>. Definition: <text>. Source of the definition: <column description / your wording>.
   (Where you worded it yourself, say "draft, confirm with the business".)

Data Agent <Name>: <purpose in one line>
  Sources: semantic model (<tables>), warehouse (<tables, none with PII>).
  Example questions to cover: <3 to 6, in the words people use>.

Open questions (only what the data can't answer):
1. <question>. Recommend: <answer>.

Your next step: reply "build all" (or the numbers you want), or change the list.
```

5. **Stop.** Don't create any file until the user replies.

## Phase 2: Build (only what the user confirmed)

1. Edit the gold specs: add `measures:` (with `description`, and `dax:` when not a plain aggregate), `synonyms:` and `ai_instructions:` the user confirmed. Mark draft definitions with `TODO(confirm with the business)` in the description and list them.
2. Write `models/agents/<Name>.yml`: description, instructions, sources, and three or more examples as T-SQL over `{{ ref() }}`. Warehouse tables must have no PII columns.
3. `python -m fde render`, then `python -m fde check` (rules A1 to A7 must pass).
4. With a dev workspace: `python -m fde deploy --target dev --notebooks-only`, then `python -m fde test-agent --target dev`. Report each failing example with its error. Don't weaken or delete an example to make it pass.
5. Tell the user what only a person can do in Fabric: confirm the semantic model refreshes (Direct Lake), review it, publish the Data Agent, and ask it the example questions to compare the answers.

Report the columns you kept out of the AI layer because of PII, so the user can correct them. End with the finish block from `AGENTS.md`.
