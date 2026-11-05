# START HERE: Build a Fabric data engineering project with the Copilot agent

This guide takes you from nothing to tested silver and gold tables in Microsoft Fabric, using GitHub Copilot in VS Code. Fabric runs the code: PySpark notebooks on a Lakehouse for silver, T-SQL stored procedures on a Warehouse for gold. dbt is not used. The agent writes table specs, and the `fde` toolkit turns them into notebooks and procedures, deploys them and tests them. `fde` stands for **Fabric Data Engineering**; you run it as `python -m fde`, much as you would run `dbt`.

Read it top to bottom the first time. Each step says what to do, what you should see, and what to do if you don't. A worked example (insurance policies and agents) is in `examples/insurance/`; look at it whenever you wonder what a spec should look like.

## Starting a new project from this kit

1. **Clone the kit into a short folder** (not OneDrive, to avoid Windows long-path errors). In PowerShell:

```powershell
git clone <kit repo address> C:\dev\my-fabric-project
```

2. **Disconnect it from the kit and connect it to your own repo** before your first commit, so a push never goes to the kit:

```powershell
cd C:\dev\my-fabric-project
git remote set-url origin <your project repo address>
git remote -v
```

   `git remote -v` must print your project address twice. To keep it local only for now, run `git remote remove origin` instead.

3. **Publish it to your repo.** Your new, empty GitHub repo has no commits yet, so push once:

```powershell
git push -u origin main
```

   **Why does Source Control look empty?** `git clone` copies the `.git` folder along with the files, so you also get the kit's full history. Every file is already committed, and `git status` says "clean" because nothing differs from the last commit. The Source Control panel in VS Code and GitHub Desktop only lists uncommitted changes, so it shows nothing. Changing `origin` only changes where `push` and `pull` go; it does not touch the history. To check the files are tracked, run `git ls-files | Measure-Object -Line`.

   **Want a fresh start with none of the kit's history?** Run this instead of the push above. It deletes the existing history, so only do it if you are sure:

```powershell
Remove-Item -Recurse -Force .git
git init -b main
git add .
git commit -m "Initial commit"
git remote add origin <your project repo address>
git push -u origin main
```

4. **Open the folder in VS Code** (File → Open Folder) and follow this guide from step 1.

## The whole journey at a glance

| # | Step | You run | Result |
| --- | --- | --- | --- |
| 1 | VS Code settings (once per computer) | Edit the VS Code settings file | Copilot reads `AGENTS.md` and shows `/` prompts |
| 2 | Install the tools | `pip install -r requirements.txt`, ODBC Driver 18 | `python -m fde --help` works |
| 3 | Create the Fabric items | Fabric portal | Workspace with `lh_bronze` (data loaded), `lh_silver`, `wh_gold` |
| 4 | Connect | Two environment variables, `python -m fde debug` | The toolkit can reach the workspace |
| 5 | Shared library | `python -m fde build-common`, Fabric portal | Environment `env_data_engineering` with the wheel |
| 6 | Scaffold | **`/scaffold-fabric-project`** | Source specs and one silver table per bronze table, built and tested in `lh_silver` |
| 7 | Integrated silver | **`/build-intermediate`** | Joined, business-rule silver tables in `lh_silver` |
| 8 | Gold | **`/build-marts`** | `Dim` and `Fact` tables, views and load procedures in `wh_gold` |
| 9 | Health check | **`/project-check`** | List of problems to fix |
| 10 | Daily pipeline | Fabric portal, once | `pl_daily_load` with 5 activities |
| 11 | Information Matrix | **`/information-matrix`** | An Excel workbook in `target/` |
| 12 | AI layer (optional) | **`/build-ai-layer`** | A semantic model and a Data Agent, ready to publish |

Always work in **Copilot Chat, Agent mode**, start a **new chat for each prompt**, and use a strong model.

## Choosing a model

Use the large, full-size models (for example Claude Sonnet or Opus, or the top-tier GPT models your account offers). Avoid the small, fast ones (names with Haiku, mini, flash or lite). Each prompt asks the agent to follow a long rulebook, run many commands in order and stop at the right moment. Small models take many more steps, miss rules and give up on problems. Strong models cost more credits per message; a scaffold or build prompt is worth it.

## Using chats

- **A new `/prompt` means a new chat.** Click **+** (New Chat) at the top of the Copilot Chat panel, then check the mode is still **Agent** and the model is still the strong one.
- **A reply to something the agent just asked goes in the same chat.** For example, `build 1 and 2` after `/build-intermediate` proposes, or `fix 1` after `/project-check`.

## How the agent works (read this once)

- **`AGENTS.md`** holds the rules Copilot follows: layers, naming, tests, PII, and how to check data. Copilot reads it automatically.
- **You decide, Copilot proposes.** Business rules, units and the meaning of codes are yours. Copilot writes `TODO(...)` where it can't tell, and never invents keys, ids or meanings.
- **Specs in, code out.** Copilot writes `models/**/*.yml` and `models/**/*.sql`. `python -m fde render` writes the notebooks (`fabric/`) and the gold T-SQL (`gold/`). Those files are committed so reviewers see what runs, but nobody edits them by hand.
- **Every prompt ends with "Your next steps".** Do those in order.
- **Use the `dev` target only.** `test` and `prod` refuse writes from a laptop.

## 1. Turn on the VS Code settings

A one-time change to VS Code itself (not typed in Copilot chat):

1. `Ctrl+Shift+P` → **Preferences: Open User Settings (JSON)**.
2. Add these two lines inside the `{ }` (every line except the last needs a comma):

```json
"chat.useAgentsMdFile": true,
"chat.promptFiles": true
```

3. Save. If `chat.promptFiles` shows "Unknown configuration setting", delete that line; your VS Code no longer needs it.

**Check it worked.** Open Copilot Chat (`Ctrl+Alt+I`), switch to **Agent**, type `/`. You should see `scaffold-fabric-project`, `build-intermediate`, `build-marts`, `project-check`, `information-matrix` and `build-ai-layer`.

## 2. Install the tools

1. **Python 3.10 or later.** `python --version`.
2. **ODBC Driver 18 for SQL Server** (the toolkit talks T-SQL to the Warehouse through it). Check with:

```powershell
python -c "import pyodbc; print(pyodbc.drivers())"
```

   If `ODBC Driver 18 for SQL Server` is not in the list, install it (Windows):

   1. Open a terminal in VS Code (`` Ctrl+` ``).
   2. Run:

      ```powershell
      winget install Microsoft.msodbcsql.18
      ```

      Accept the licence prompt. If `winget` is not available, download **ODBC Driver 18 for SQL Server (x64)** from Microsoft Learn (search "Download ODBC Driver for SQL Server"), run the `.msi` and accept the defaults.
   3. **Close and reopen VS Code**, then run the check above again. The list must now contain `ODBC Driver 18 for SQL Server`.

   If the list still shows only older drivers, check that your Python is 64-bit (`python -c "import struct; print(struct.calcsize('P')*8)"` prints `64`); the driver is 64-bit.

3. **The kit's Python packages**, from the repo root:

```powershell
pip install -r requirements.txt
python -m fde --help
python -m pytest -q
```

   The tests run offline against `examples/insurance` and should all pass.

4. **Optional: Azure CLI** (`winget install Microsoft.AzureCLI`). With it, `az login` signs the toolkit in. Without it, the toolkit opens a browser sign-in when it needs one.

## 3. Create the Fabric items

You need a Fabric capacity (a trial capacity is fine for a test) and a workspace on it. Item names must be exactly these (they are set in `fde.yml`):

1. **Workspace:** for example `<Project> Data - DEV`, on the capacity.
2. **`lh_bronze`**: New item → Lakehouse. Load your source data into it as **tables**, one schema per source system. In production a pipeline does this; for a sandbox, load the CSV files by hand (section 3a below).
3. **`lh_silver`**: New item → Lakehouse, with **Lakehouse schemas** ticked. Leave it empty; the silver notebooks create the schemas and tables.
4. **`wh_gold`**: New item → Warehouse. Leave it empty; `fde deploy` creates the schemas, tables, views and procedures.

| Layer | Where it lives | Created by |
| --- | --- | --- |
| Bronze | `lh_bronze.<source>.<table>` | you / ingestion |
| Silver source tables | `lh_silver.<source>.<Table>` | the silver notebooks |
| Silver integrated tables | `lh_silver.<domain>.<Table>` | the silver notebooks |
| Gold | `wh_gold.<domain>.<Dim/Fact Table>` | `fde deploy` + the load procedures |
| Gold logic views | `wh_gold.stage.<Table>Source` | `fde deploy` |
| Test results | `wh_gold.ops.DataQualityResult` | `fde deploy` + the pipeline |

### 3a. Sandbox: build the bronze layer by uploading CSV files

Bronze is normally loaded by Fabric pipelines. In a sandbox you can do it by hand. Do this once per source system.

1. **Prepare the files.** One CSV per source table, with a header row, UTF-8 encoding. Use PascalCase or snake_case column names without spaces or special characters (Delta tables reject spaces and `,;{}()=` in column names). Name each file after the table it will become, for example `Policy.csv`.
2. **Create the lakehouse with schemas.** In the workspace: **New item → Lakehouse**, name it `lh_bronze`, and tick **Lakehouse schemas**. (Without schemas, tables land in `dbo`; then pass `--schema dbo` in `/scaffold-fabric-project`.)
3. **Create a schema per source system.** In the lakehouse explorer, hover over **Tables** → **...** → **New schema**. Use the source name in snake_case, for example `policy_admin`.
4. **Upload the files.** Hover over **Files** → **...** → **Upload** → **Upload files** (or **Upload folder**), pick your CSVs. They appear under **Files**. Put them in a sub-folder per source (**Files → ... → New subfolder**) to keep them tidy.
5. **Load each file to a table.** Right-click the CSV under **Files** (or its **...** menu) → **Load to Tables** → **New table**.
   - Table name: the target name, for example `Policy`.
   - Schema: the source schema from step 3.
   - Tick **Use header for column names**, check the separator (`,`), and choose **Overwrite** the first time.
   - Select **Load**. Wait for the notification.
6. **Check the result.** Expand **Tables → `<source>`**: each table should show with its columns and a row count in the preview. Compare the row count to the CSV.
7. **Optional: `_ingested_at`.** Freshness tests and incremental loads use an `_ingested_at` timestamp. Load to Tables cannot add it. Skip it in a sandbox and run builds with `--skip-source-tests` (see Troubleshooting), or add the column later with a notebook.

**Known limits of Load to Tables:** it infers column types (dates may arrive as strings; that is fine, silver casts them); it is not scheduled; to reload, upload the new file and choose **Overwrite**.

## 4. Connect the toolkit to the workspace

Everything below runs in the **VS Code terminal** (`` Ctrl+` ``, PowerShell), opened at the repo root.

### 4a. Sign in with the Azure CLI (recommended)

1. Install it if needed, then **reopen VS Code**:

   ```powershell
   winget install Microsoft.AzureCLI
   az --version
   ```

2. Sign in with the account that has access to the sandbox workspace:

   ```powershell
   az login
   ```

   A browser opens; pick the account and approve. If the account is in several tenants, the terminal asks you to choose a subscription: press Enter for the default (Fabric does not need an Azure subscription). If no browser can open, use `az login --use-device-code` and follow the printed instructions.
3. Confirm who you are:

   ```powershell
   az account show --query user.name -o tsv
   ```

   If your Fabric tenant differs from the default, sign in to it directly: `az login --tenant <tenant-id-or-domain>`.

### 4b. Find the two values

- **SQL endpoint:** open `wh_gold` in the Fabric portal → **Settings** (or the ... menu) → **SQL connection string**. Copy the host, which looks like `xxxxxxxx.datawarehouse.fabric.microsoft.com`.
- **Workspace id:** open the workspace; the id is the GUID in the browser address after `/groups/`.

### 4c. Set them as environment variables

The values live in environment variables, never in files. Set them for your user (once), then **close and reopen VS Code** (`setx` does not change the terminal that is already open):

```powershell
setx FABRIC_DEV_SQL_ENDPOINT "xxxxxxxx.datawarehouse.fabric.microsoft.com"
setx FABRIC_DEV_WORKSPACE_ID "00000000-0000-0000-0000-000000000000"
```

### 4d. Test the connection

After reopening VS Code and the terminal, check the variables are set, then run the toolkit check:

```powershell
echo $env:FABRIC_DEV_SQL_ENDPOINT $env:FABRIC_DEV_WORKSPACE_ID
python -m fde debug --target dev
```

You should see your user name, the items `lh_bronze`, `lh_silver` and `wh_gold`, and `debug: connection OK`. The first run may open a browser sign-in; use the account that has access to the workspace.

| What you see | Fix |
| --- | --- |
| `set FABRIC_DEV_SQL_ENDPOINT ...` | You didn't reopen VS Code after `setx`, or the variable name is wrong |
| `Missing items ...` | Create the item (step 3) or fix the name in `fde.yml` |
| `Data source name not found` | ODBC Driver 18 is not installed (step 2) |
| Login error | `az login`, or close other browser sign-ins and retry |

## 5. Install the shared library in the workspace

Every silver notebook imports `fabric_de_common` (shared read, conform, MERGE and audit-column code). It lives in a Fabric Environment:

1. Build the wheel:

```powershell
python -m fde build-common
```

   It writes `target/dist/fabric_de_common-0.1.0-py3-none-any.whl`.

2. In the workspace: New item → **Environment**, name it `env_data_engineering`.
3. In the Environment: **Custom libraries** → **Upload** → the `.whl` file. Then **Save** and **Publish** (publishing takes a few minutes).
4. Workspace settings → **Data Engineering/Science** → **Spark settings** → **Environment** → set the default environment to `env_data_engineering`. Now every notebook in the workspace can `import fabric_de_common`.

When the library changes (rarely), bump the version in `common/pyproject.toml` and `common/fabric_de_common/__init__.py`, rebuild, upload and publish again.

### Alternative: install the wheel in each notebook (no Environment)

Use this when the workspace is shared and you must not change its default Environment (step 4), for example a shared sandbox. Skip steps 2 to 4 and do this instead:

1. Run `python -m fde build-common`.
2. In the silver Lakehouse, open **Files**, create a folder `libs` and upload the `.whl` there.
3. In `fde.yml`, under `silver:`, set the wheel path and re-render:

```yaml
silver:
  install_wheel: /lakehouse/default/Files/libs/fabric_de_common-0.1.0-py3-none-any.whl
```

```powershell
python -m fde render
```

Every silver notebook then starts with a cell that installs the library for that session only, and does nothing if it is already there. Notes:

- Change the file name in `install_wheel` when you bump the library version, and upload the new wheel.
- Each notebook start spends a few seconds on the install, so for a daily production pipeline prefer the Environment.
- The wheel's dependencies must be installable from the internet, and the path only resolves while the silver Lakehouse is the notebook's default (the renderer sets that).

## 6. Scaffold the project: `/scaffold-fabric-project`

Creates the source specs and one silver source table per bronze table, then deploys, runs and tests them.

1. In a new chat (Agent mode) type `/scaffold-fabric-project`.
2. Answer its inputs: the project name, the bronze source systems (schema names in `lh_bronze`), the gold domains (for example `sales, distribution`), an Information Matrix path (or `none`), and a **data dictionary path** if you have one. The dictionary's text becomes the column descriptions; anything it doesn't cover becomes `TODO(...)`.
3. It ends with a short summary and **Your next steps**. The full detail is in `docs/scaffold_report.md`, with every `TODO` sorted into *Blocking*, *Data questions* and *Deployment placeholders*.

Then check for yourself:

```powershell
python -m fde check
python -m fde test --target dev --layer silver
```

In Fabric, open `lh_silver`: you should see one schema per source with the silver tables, each with the four audit columns at the end.

## 7. Integrated silver tables: `/build-intermediate`

Integrated silver tables hold joins and business rules (dbt calls this the intermediate layer). Two phases with a stop between them:

1. New chat → `/build-intermediate` → your domain (for example `sales`).
2. **Phase 1, it proposes and changes no files.** It describes each silver table, suggests integrated tables, and lists open questions, each with the evidence from a counts-only query and a recommended answer.
3. **You decide.** Reply, for example, `build 1 and 2`, and answer what you can.
4. **Phase 2, it builds** the confirmed tables (spec + Spark SQL), renders, deploys, runs and tests them.

## 8. Gold tables: `/build-marts`

Gold holds the `Dim` and `Fact` tables people query, in the Warehouse. Same two phases:

1. New chat → `/build-marts` → your domain.
2. It plans dimensions (with SCD type 1 or 2) and facts (grain, dimension keys, measures), checks the data, lists the columns it would mark as personal data, and stops.
3. Reply `build 1 and 2`. It writes the spec and the T-SQL SELECT for each table, renders the table DDL, the `stage` view and the `Load<Table>` procedure, deploys, loads and tests.

Check in Fabric: open `wh_gold`, schema `<domain>`. Every dimension has a row with `_SK = -1` (the unknown member); facts point there when a key has no dimension row, and `python -m fde test` reports how many.

## 9. Check the project: `/project-check`

New chat → `/project-check`. It runs `python -m fde check` (layer, naming, type and completeness rules, plus "are the rendered files up to date") and the dev data tests, then lists what to fix, most serious first. It fixes nothing until you reply, for example `fix 1`.

## 10. Build the daily pipeline (once)

The pipeline's shape never changes as you add tables: everything that changes is inside the notebooks and procedures the kit renders. Create it once per workspace:

1. New item → **Data pipeline** → `pl_daily_load`.
2. **Parameters** (pipeline canvas, empty area → Parameters): `LoadDate` (String, default empty).
3. Wherever the table below says *the LoadDate expression*, use this (yesterday unless a date is passed in): `@if(empty(pipeline().parameters.LoadDate), formatDateTime(addDays(utcNow(), -1), 'yyyy-MM-dd'), pipeline().parameters.LoadDate)`.
4. Add five activities, each on success of the previous one:

| # | Activity | Settings |
| --- | --- | --- |
| 1 | Stored procedure | Warehouse `wh_gold`, procedure `ops.RunDataQualityTests`, parameters `Layer` = `source`, `LoadStepID` = `@pipeline().RunId` |
| 2 | Notebook | `nb_ops_run_silver`, base parameters `load_date` = the LoadDate expression, `load_step_id` = `@pipeline().RunId`, `full_refresh` = `false` |
| 3 | Stored procedure | `ops.RunDataQualityTests`, `Layer` = `silver`, `LoadStepID` = `@pipeline().RunId` |
| 4 | Stored procedure | `ops.RunGoldLoads`, `LoadDate` = the LoadDate expression, `LoadStepID` = `@pipeline().RunId` |
| 5 | Stored procedure | `ops.RunDataQualityTests`, `Layer` = `gold`, `LoadStepID` = `@pipeline().RunId` |

5. Add a failure notification (Teams or Outlook activity on failure) and a schedule (after bronze ingestion finishes).
6. Run it once by hand and check `select * from ops.DataQualityResult` in `wh_gold`.

## 11. Build the Information Matrix: `/information-matrix`

After silver and gold build and `/project-check` is clean: new chat → `/information-matrix` → a version (for example `Dev`), your name, and `none` for the previous matrix. It builds `target/Information Matrix Dev.xlsx` from the specs, profiles the data read-only (counts and non-PII examples), and lists what only people can fill in. Never edit or commit the workbook. See `information_matrix_instructions.md`.

## 12. AI layer: `/build-ai-layer`

After gold builds and its tests pass: new chat → `/build-ai-layer`. Copilot first proposes (measures, what stays out because of personal data, the questions the agent should answer) and stops. Reply `build all` and it writes the measures, synonyms and a Data Agent spec, then renders:

- `fabric/sm_<project>.SemanticModel/`: a Direct Lake semantic model over `wh_gold`. Measures come from the `measures:` on facts, relationships from `references:`. Personal-data columns are left out.
- `fabric/da_<name>.DataAgent/`: a Data Agent (draft) with its instructions, the tables it may see and your example questions.

Then, in your own terminal:

```powershell
python -m fde deploy --target dev --ai-only      # publishes the semantic model and the agent
python -m fde test-agent --target dev            # runs every example question read-only
```

In Fabric: open the semantic model (check it refreshes), open the Data Agent, ask it the example questions, compare the answers with `test-agent`, then publish it. Data Agents need a paid Fabric capacity (F2 or larger) and the tenant settings for Copilot and Data Agents, which your Fabric admin controls. Data Agent Git support is in preview: see the standards, section 15.

## Rules Copilot follows (what to expect)

- **Layers:** silver source tables read one bronze table; integrated silver reads silver; gold reads silver and gold; everything through `{{ ref() }}`; nothing hard-codes item names.
- **No hand-written notebooks or procedures.** Specs and SELECTs only; `fde render` writes the code, to DE Policy v2.
- **Personal data:** marked `meta.pii: true` in every layer, automatically; sensitive amounts listed for your decision; values never printed.
- **Check the data first:** before asking you, Copilot runs a read-only counts query with `python -m fde show` and shows the numbers.
- **No guessing:** unknown keys, ids and meanings become `TODO(...)` in the report.

## Daily commands

```powershell
python -m fde check                                   # rules + render drift (offline)
python -m fde render                                  # regenerate notebooks and T-SQL
python -m fde build --target dev                      # deploy, run silver, load gold, test
python -m fde build --target dev --layer gold --skip-deploy
python -m fde test --target dev --select FactNewBusiness
python -m fde deploy --target dev --ai-only           # semantic model + Data Agents
python -m fde test-agent --target dev                 # Data Agent example questions
python -m fde show "select count(*) as n from {{ ref('sales.FactNewBusiness') }}"
python -m fde ls --tests
```

## Troubleshooting

| What you see | Cause | Fix |
| --- | --- | --- |
| `R1 out of date: ...` in `fde check` | A spec changed (or someone edited a rendered file) | `python -m fde render`, commit the result |
| `No module named fabric_de_common` in a notebook run | Environment missing or not the workspace default | Step 5 |
| Silver tests fail right after the silver run, gold sees old data | SQL endpoint not yet synced | The silver run refreshes it; if the refresh call fails, see the standards section 15 (spike item 3) |
| `fabric-cicd` errors on deploy | Version or parameter syntax | Pin the version you tested in `requirements.txt`; check `fabric/parameter.yml` |
| Source freshness fails in dev | Dev bronze is older than 48 hours | `--skip-source-tests` in dev; never in test or prod |
| `target 'test' is protected` | Writes to test/prod only come from the release pipeline | Use `--target dev` |
| A prompt runs for a very long time | A command waits for your approval, or a browser sign-in is hidden | Look for **Allow** in the chat and for a sign-in tab |
| `/` shows no prompts | Settings or folder not loaded | Redo steps 1 and 2 of this guide; reload VS Code |

Reference docs: `AGENTS.md` (rules), `fabric_engineering_standards.md` (rationale and spike list), `examples/insurance/` (a complete worked example).
