# Dual-Track Build — Track A + Track B with 30-Day Azure Archive

## How the two tracks work together

| Track | Source | Answers |
|-------|--------|---------|
| **A — Transfer stats** | Splunk CSV + git + parsed log **signals** | "Similar promotions failed prod X% of the time" |
| **B — Vector** | **All archived log text** (build + security + deploy) | "This log error looks like past prod failures" |
| **Combined** | `60% × A + 40% × B` (configurable) | Single enterprise gate score |

Both tracks use the **same** `data/log_archive/` — Track A extracts regex signals; Track B embeds log chunks.

---

## One-time setup

```bash
cd ~/Projects/pipeline-risk-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-vector.txt   # ChromaDB + embeddings
cp .env.example .env
```

### Point at your existing 30-day Azure files

**Option A — symlink (no copy):**
```bash
ln -s /path/to/your/existing/azure/logs data/log_archive
```

**Option B — copy into project:**
```bash
cp -r /path/to/your/azure/logs/* data/log_archive/
```

**Expected layout** (per execution):
```
data/log_archive/
  8098001/
    build.log
    securityTests.log
    deploy/deploy.log
```

Or keyed by share UUID — `scan-archive` maps via `share-names.csv`.

---

## Build both tracks (single command)

```bash
# 1. Splunk data (API or manual CSVs)
python3 cli.py fetch-splunk

# 2. Verify archive coverage
python3 cli.py scan-archive

# 3. Build Track A + Track B
python3 cli.py build
```

Or step by step:
```bash
python3 cli.py index --rebuild    # same as build (includes vector if ENABLE_VECTOR_TRACK=true)
```

---

## Score (all three outputs)

```bash
python3 cli.py score --dev-exec 8098001
```

Report includes:
- **Track A** — structured probability + pair/rule drivers
- **Track B** — vector neighbors + similarity-based probability
- **Combined** — weighted gate score (`TRACK_A_WEIGHT` / `TRACK_B_WEIGHT`)

---

## What improves over time

1. **More Splunk history** → more dev→prod pairs → Track A stabilizes
2. **More archived logs** → more vector chunks → Track B neighbors improve
3. **Weekly `build`** → both indexes refresh
4. **`prediction_log.jsonl`** → measure which track was right → tune weights

---

## Env for dual-track

```bash
LOG_ARCHIVE_DIR=data/log_archive
ENABLE_VECTOR_TRACK=true
SKIP_AZURE_LIVE=true          # use archive only (you already have 30 days)
TRACK_A_WEIGHT=0.6
TRACK_B_WEIGHT=0.4
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `coverage_pct: 0` | Wrong `LOG_ARCHIVE_DIR` or folder names don't match executionId |
| Vector chunks: 0 | `pip install -r requirements-vector.txt` |
| Track A pairs: 0 | Set git creds for commit correlation |
| Tracks disagree | Normal — review both; combined uses weighted blend |
