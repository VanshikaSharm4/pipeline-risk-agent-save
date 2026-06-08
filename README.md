# Pipeline Risk Agent

Dev→prod failure risk for **Adobe Cloud Manager Program 19905**.

```bash
cd ~/Projects/pipeline-risk-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
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



Without Splunk creds, use manual CSVs only. Without Azure creds, archive step is skipped.

## Azure logs vs vector DB — keep both

**Recommendation: store raw logs in the project, then build vector DB from them.**

| Approach | Pros | Cons |
|----------|------|------|
| **Keep `data/log_archive/`** | Re-build vector after model change; debug neighbors; new regex patterns; audit | Uses disk (~MB per execution) |
| **Vector only, delete files** | Saves disk | Cannot re-embed; cannot debug; lost detail forever |


