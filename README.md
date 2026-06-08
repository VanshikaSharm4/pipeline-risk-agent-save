# Pipeline Risk Agent

Dev→prod failure risk for **Adobe Cloud Manager Program 19905**.

| Pipeline | ID |
|----------|-----|
| Dev-pipeline | `47202398` |
| Production Pipeline | `2357452` |

Ingests **all executions** from Splunk (API or CSV). Archives Azure logs locally before the **15-day purge** for vector indexing.

## Quick start

```bash
cd ~/Projects/pipeline-risk-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```bash
SPLUNK_USERNAME=your_adobe_email@adobe.com
SPLUNK_PASSWORD=your_password
AZURE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
LOG_ARCHIVE_DIR=data/log_archive
```

## Splunk API (your curl equivalent)

Fetches **both** dev and prod pipelines (same SPL, `pipelineId` swapped):

```bash
python3 cli.py fetch-splunk
```

Writes `data/splunk_exports/pipelines-list.csv`. Equivalent to your curl against `splunk-api.or1.adobe.net` with `-90d` window.

You still need `first-failed-steps.csv` and `share-names.csv` from Cloud Manager Helper (or existing exports).

## Azure archive (before logs vanish)

```bash
python3 cli.py archive-azure --pipeline all
# Or limit: python3 cli.py archive-azure --pipeline dev --limit 10
```

Saves under `data/log_archive/{executionId}/build.log`, `securityTests.log`, `deploy/deploy.log`.

Then rebuild index (optionally with vector):

```bash
pip install -r requirements-vector.txt
ENABLE_VECTOR_TRACK=true python3 cli.py index --rebuild
```

## Dashboard (dev / prod / archive UI)

```bash
streamlit run dashboard/app.py
```

Tabs:

1. **Splunk pipelines** — dev & prod tables, “Fetch from Splunk API” button  
2. **Azure archive** — archived files, bulk fetch button  
3. **Index & score** — rebuild index, score an execution  
4. **How to run** — this guide inline  

## CLI reference

```bash
python3 cli.py verify splunk
python3 cli.py list --pipeline dev
python3 cli.py list --pipeline prod
python3 cli.py fetch-splunk
python3 cli.py archive-azure --pipeline all
python3 cli.py index --rebuild --no-vector
python3 cli.py history
python3 cli.py score --dev-exec 8098001
python3 cli.py backtest
```

## Typical workflow

1. `fetch-splunk` — refresh pipeline list from API  
2. Ensure `share-names.csv` + `first-failed-steps.csv` are current  
3. `archive-azure` — pull logs into `data/log_archive/`  
4. `index --rebuild` — build pairs + stats (+ vector if enabled)  
5. `score --dev-exec <id>` — dual-track risk report  

## Config notes

| Variable | Default | Meaning |
|----------|---------|---------|
| `HISTORY_WINDOW_DAYS` | `0` | Use all rows in CSV; set `30` to trim by age |
| `SKIP_AZURE_LIVE` | `true` | Index uses archive only; set `false` for live fetch |
| `SPLUNK_EARLIEST` | `-90d` | Splunk API time range |
| `ENABLE_VECTOR_TRACK` | `false` | Enable Track B (needs `requirements-vector.txt`) |

## Required `.env` credentials

| Variable | Required for | Same as |
|----------|--------------|---------|
| `SPLUNK_USERNAME` / `SPLUNK_PASSWORD` | `fetch-splunk`, dashboard Splunk button | `curl -u user:pass` |
| `AZURE_CONNECTION_STRING` | `archive-azure` | Azure File Share |
| `CM_GIT_*` + `GIT_LOCAL_DIR` | commit correlation, module analysis | CM Git access |

Without Splunk creds, use manual CSVs only. Without Azure creds, archive step is skipped.

## Azure logs vs vector DB — keep both

**Recommendation: store raw logs in the project, then build vector DB from them.**

| Approach | Pros | Cons |
|----------|------|------|
| **Keep `data/log_archive/`** | Re-build vector after model change; debug neighbors; new regex patterns; audit | Uses disk (~MB per execution) |
| **Vector only, delete files** | Saves disk | Cannot re-embed; cannot debug; lost detail forever |

Workflow:

1. `archive-azure` → saves to `data/log_archive/{executionId}/` **inside the project**
2. `index --rebuild` → reads archive → builds `data/index/vector_store/`
3. **Keep archive files** — vector is a *derived* index, not a backup

Azure purges at 15 days; your project archive does not. Re-run `archive-azure` weekly for new executions.

`data/log_archive/` is gitignored (large files) but lives on disk in the project folder.

## Security

- No cloud LLM — git/code stays local  
- Splunk/Azure/Git credentials only in `.env` (gitignored)  
# pipeline-risk-agent-save
