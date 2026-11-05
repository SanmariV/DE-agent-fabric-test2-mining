---
applyTo: "models/silver/**"
---

# Silver (Lakehouse, PySpark notebooks)

The folder is the schema; the file name is the table. Each silver table is rendered into one notebook, `nb_silver_<schema>_<table>`.

## Source tables: `models/silver/<source>/<Entity>.yml` (no `.sql`)

There is one per bronze table. A source table may:

- rename and cast
- trim and upper-case codes
- handle nulls (`'UNKNOWN'` for missing codes)
- build `Is`/`Has` flags

It never joins, aggregates or applies business rules.

```yaml
description: >
  One row per customer as currently held in the CRM. Grain = Customer_BK.
source: {source: crm, table: customer}
load: {mode: incremental, column: _ingested_at, lookback_days: 3}   # or {mode: full}
dedupe_order_by: ["_ingested_at desc"]      # keep the latest row per key
columns:
  - name: Customer_BK
    data_type: string
    expression: upper(trim(customer_id))    # Spark SQL over bronze columns
    business_key: true
    description: Customer number from the CRM.
  - name: CustomerName
    data_type: string
    expression: trim(name)
    description: Customer full name.
    meta: {pii: true}
  - name: IsActive
    data_type: boolean
    expression: status = 'A'
    description: True while the customer has an active relationship.
```

- Spark types: `string`, `boolean`, `int`, `bigint`, `smallint`, `decimal(p,s)`, `date`, `timestamp`, `binary`. Money is `decimal(18,2)`.
- Carry another entity's business key under that table's key name (`Agent_BK` on `Policy`). Only the table's own key is `business_key: true`.
- Keep the load timestamp as a column (`IngestedTimestamp`) when it helps incremental reads downstream.
- If you can't tell what a column means, write `description: TODO(meaning of <bronze column>)` and list it. Never guess a business key. Ask, or list it.

## Integrated tables: `models/silver/<domain>/<Entity>.yml` + `.sql`

These hold joins, business rules and re-graining (dbt's "intermediate" layer).

- The `.sql` is a Spark SQL SELECT over `{{ ref('schema.Table') }}`. It returns exactly the spec's columns and may use `:load_date` for date windows.
- Name tables after the result (`NewBusinessPolicy`, `CommissionSplit`), not the operation.
- Read silver only, with at most about 4 to 6 inputs. Put each business rule in its own table so it can be tested.
- Unconfirmed rules: implement the recommended answer only if the user accepted it. Otherwise write `TODO(...)` in the description and list it.

## Tests

Key tests are implied. Add:

- `accepted_values` on codes
- `accepted_range` on amounts
- `expression` for row rules

Then run `python -m fde render` and `python -m fde check`.
