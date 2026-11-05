# Scaffold report: open_database_mine_production

## Files created or changed

**Project settings**
- `fde.yml`: `project: open_database_mine_production`
- `models/gold/production/.gitkeep`, `models/gold/facilities/.gitkeep`
- `reference/business_glossary.csv`: already header-only, unchanged

**Sources**
- `models/sources/dbo.yml` (12 tables, 139 columns; generated from `lh_bronze.dbo`, descriptions added)

**Silver source tables** (`models/silver/dbo/`)

| Bronze table | Silver table | Business key |
| --- | --- | --- |
| facilities | `Facility` | `Facility_BK` (facility_id) |
| material_ids | `Material` | `Material_BK` (material_id) |
| source_ids | `DataSource` | `DataSource_BK` (source_id) |
| capacity | `FacilityCapacity` | `FacilityCapacity_BK` (id) |
| coal | `CoalProduction` | `CoalProduction_BK` (id) |
| commodities | `CommodityProduction` | `CommodityProduction_BK` (id) |
| minerals | `MineralProduction` | `MineralProduction_BK` (id) |
| ownership | `FacilityOwnership` | `FacilityOwnership_BK` (id) |
| processing | `FacilityProcessing` | `FacilityProcessing_BK` (id) |
| reserves | `MaterialReserve` | `MaterialReserve_BK` (id) |
| transport | `TransportFlow` | `TransportFlow_BK` (id) |
| waste | `WasteStream` | `WasteStream_BK` (id) |

All keys were checked against bronze: `count(*) = count(distinct key)` and no nulls in every table. All tables use `load: {mode: full}` and need no `dedupe_order_by`.

**Rendered** (by `python -m fde render`): 12 silver notebooks, `nb_ops_run_silver`, `gold/ops/procedures/RunDataQualityTests.sql`.

## TODOs left

### 1. Blocking
- **`FABRIC_DEV_WORKSPACE_ID` is not a valid GUID** (set, 69 characters). `fde build` stops with "The provided workspace_id is not a valid guid." Set it to the workspace GUID only (not a URL or path), then run `python -m fde build --target dev --layer silver`. See step 4 of `START_HERE.md`.

### 2. Data questions
- `models/silver/dbo/CommodityProduction.yml`: `id_minerals` (dictionary calls it `minerals_id`) is meant to join to `minerals`; 2,373 of 9,426 rows have no match on `minerals.id`. Which key does it reference?
- `models/silver/dbo/FacilityProcessing.yml`: `input` / `output` are free text and match no `material_id`. How should they map to `Material`?
- `models/silver/dbo/TransportFlow.yml`: 165 of 941 `product` values have no match in `material_ids`.
- Load timestamp: bronze has no `_ingested_at` or similar column, so freshness cannot run.

### 3. Deployment placeholders
- None created by this task.

## Needs a decision
- **Freshness rule**: removed from `models/sources/dbo.yml` because `_ingested_at` does not exist (rule S7 warns). Recommend: leave as is; the dataset is a one-off load.
- **Facility `fid`** has no dictionary entry and was not carried to silver. Recommend: leave out (row id of the GeoPackage).
- **Dictionary entry without bronze column**: `minerals_id` (bronze has `id_minerals`).
- **Dictionary vs data differences** (no `accepted_values` added):
  - `coal.type` holds `Coal mined` / `Clean coal`; the dictionary lists only ore types.
  - `type_mining` holds `Surface` / `Underground`; the dictionary says `Open pit` / `Underground`.
  - `facility_type` holds combinations (for example `Refinery, Smelter`) plus `Company`, `Region`, `Concentrator`; the dictionary lists `Refinery`, `Smelter`.
  - `activity_status` is null for 2,344 of 2,413 rows and has mixed case and free text (`stopped 31.12.2013`).
  - `export` and `incl_purchased` have mixed case (`Yes` / `yes`); mapped to booleans.
- `Facility` rows with type `Company` (10) and `Region` (13) are not facilities. Recommend: decide in gold whether to filter them.
- **Float NaN in bronze**: `commodities.grade_ppm` holds NaN, which the Warehouse SQL endpoint cannot read (so `fde show` fails on that column). Silver casts to `decimal`; check that NaN becomes null once the build runs.
- `processing.metal_payable_tonnes` is text in bronze; silver uses `try_cast`.
- `materials_covered.xlsx` has no description column and was not used as a dictionary.

## Dictionary coverage
- Described from `variables_descriptions.xlsx`: every bronze column except `id_minerals` and `fid` (about 137 of 139).
- Still `TODO`: `id_minerals`, `processing.input`, `processing.output`, `transport.product` (join meaning only).

## PII columns marked
- None. `Owners`, `Operators` hold company names; `LocationGeometry` is a mine location. Confirm no person names appear in `Owners` / `Operators`.

## Commands (step 5)
- `python -m fde render`: 27 files changed, now up to date.
- `python -m fde check`: 0 errors, 1 warning (S7, no freshness rule).
- `python -m fde build --target dev --layer silver`: **failed**, invalid `FABRIC_DEV_WORKSPACE_ID` (see Blocking).

## Next step
`/build-intermediate` for one domain (`production` or `facilities`), then `/build-marts`.
