---
applyTo: "models/**/*.yml,fde.yml"
---

# Spec YAML files

- 2-space indents and lines of 80 characters or fewer. Use `>` for long descriptions.
- Every table description states the grain: "One row per policy. Grain = Policy_BK."
- Every column has a `description` with the business meaning, unit and allowed values. "The policy id" is not enough.
- Tests:
  - column tests go under the column's `tests:`; table tests under the table's `tests:`
  - give parameters as a mapping: `- accepted_values: {values: [A, B]}`
  - use `severity: warn` only with a reason
- Never declare the columns the kit adds: `_SK`, `StartDate`, `EndDate`, `IsCurrent`, `InsertLoadStepID`, `InsertTimestamp`, `LastUpdateLoadStepID`, `LastUpdateTimestamp`.
- `fde.yml` holds item names and the names of environment variables, never hosts, ids or secrets.
- After editing, run `python -m fde render` and `python -m fde check`.
