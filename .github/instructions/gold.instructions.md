---
applyTo: "models/gold/**"
---

# Gold (Warehouse, T-SQL)

Each gold table is `models/gold/<domain>/<Table>.yml` + `<Table>.sql`. The folder is the schema. Each table is rendered into:

- a table DDL
- a `stage.<Table>Source` view that holds the SELECT
- one `Load<Table>` stored procedure (MERGE, with SCD2 for type 2 dimensions)

## Rules

- Names: `Dim<Entity>` (singular), `Fact<BusinessProcess>`, `Bridge<A><B>`. One concept, one gold table; never a team-specific copy.
- The SELECT is T-SQL:
  - it reads silver and gold through `{{ ref('schema.Table') }}`
  - it returns exactly the spec's business key and data columns
  - it has no `@parameters`, no `order by` and no non-deterministic functions
- Types: `varchar(n)`, `decimal(18,2)` for money, `decimal(18,8)` for rates, `bit`, `date`, `datetime2(6)`, `int`, `bigint`. Never `nvarchar`, `datetime`, `money` or `tinyint`.
- Dimensions set `scd_type: 1` or `2`. The kit adds `<Table>_SK`, `StartDate`/`EndDate`/`IsCurrent` (type 2), the audit columns and an unknown member row (`_SK = -1`).
- Facts reference dimensions with `<Role><DimTable>_SK` (`bigint`, `references: <domain>.<DimTable>`), resolved with a point-in-time join and `coalesce(..., -1)`:

```sql
select
    policy.Policy_BK,
    coalesce(agent.DimAgent_SK, -1) as DimAgent_SK,
    policy.AnnualPremiumAmount,
    policy.IssueDate
from {{ ref('sales.NewBusinessPolicy') }} as policy
left join {{ ref('distribution.DimAgent') }} as agent
    on agent.Agent_BK = policy.Agent_BK
    and policy.IssueDate between agent.StartDate and agent.EndDate
```

- Large facts: `load: {mode: incremental, column: IssueDate, lookback_days: 7}`.
- Financial facts: a `reconciles_to` test against a control-total table.
- Measures on facts: `measures: [{name: AnnualPremiumTotal, expression: sum(AnnualPremiumAmount), description: ...}]`. They document the Power BI semantic model. Every measure needs a description, which becomes its definition.

## Information Matrix metadata (`meta.matrix`)

Facts that only people know live in `meta.matrix`, next to the table, so the matrix script copies them instead of anyone guessing. Never invent these values. Leave them out and the gap report lists them.

```yaml
meta:
  matrix:
    name: DimCustomer              # name used in the matrix (default: table name)
    business_question: Who         # Who, What, Where, When, Why (dimensions)
    scd_type: 2
    presentation: ['data_lake', 'power_bi']
    priority: High                 # High, Medium, Low
    # facts: grain, event_frequency, refresh_frequency, group_type
columns:
  - name: CustomerName
    meta:
      pii: true                    # never sampled
      matrix:
        example: 'Thabo M***'      # synthetic, required when pii
        hierarchy: {name: Geography, level: 1}
measures:
  - name: AnnualPremiumTotal
    expression: sum(AnnualPremiumAmount)
    description: Total annualised premium.
    meta:
      matrix: {additivity: Additive, unit: Currency, priority: High, scenarios: ['actual']}
```

- Model keys:
  - dimensions: `name`, `business_question`, `scd_type`
  - facts: `grain`, `event_frequency`, `refresh_frequency`, `group_type`
  - both: `presentation`, `priority`, `ready`, `planned_release`, `comments`
- Column keys: `pii` goes directly under `meta`. Under `matrix`: `example`, `scd`, `role`, `hierarchy`, `scope_rule`, `value_rule`, `comments`, `extra: {"<exact column header>": "<value>"}`.
