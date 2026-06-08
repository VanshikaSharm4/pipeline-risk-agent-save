"""Streamlit dashboard — dev/prod pipelines, Azure archive, dual-track scoring, vector DB."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from analysis.azure_archiver import archive_all_from_csv, archive_dir, list_archived
from connectors import splunk_csv

st.set_page_config(page_title="Pipeline Risk Agent", layout="wide")
st.title("Pipeline Risk Agent — Program 19905")


def _risk_badge(risk: str) -> str:
    return {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(risk, "⚪")


def _render_track_score(label: str, track, weight: float | None = None):
    if track is None:
        st.info(f"{label}: not available")
        return
    w = f" (weight {weight:.0%})" if weight is not None else ""
    st.markdown(f"**{label}**{w}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Risk", f"{_risk_badge(track.risk)} {track.risk}")
    c2.metric("Prob", f"{track.prob:.0%}")
    c3.metric("Confidence", track.confidence)
    if track.drivers:
        for d in track.drivers[:8]:
            st.caption(f"• {d}")


@st.cache_data(ttl=120)
def load_pipeline_data():
    try:
        df = splunk_csv.load_pipelines()
        dev, prod = splunk_csv.split_dev_prod(df)
        return df, dev, prod, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), str(e)


def main():
    st.sidebar.header("Actions")
    if st.sidebar.button("Refresh data"):
        load_pipeline_data.clear()
        st.rerun()

    tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Gate ▶ Prod?",
            "Splunk pipelines",
            "Azure archive",
            "Vector DB",
            "Index & score",
            "How to run",
        ]
    )

    with tab0:
        st.subheader("Dev → Prod Gate (Track A + Track B)")
        st.caption(
            f"Program `{config.PROGRAM_ID}` · Dev `{config.PIPELINE_ID_DEV}` "
            f"→ Prod `{config.PIPELINE_ID_PROD}` · "
            f"weights A={config.TRACK_A_WEIGHT:.0%} B={config.TRACK_B_WEIGHT:.0%}"
        )

        exec_id_gate = st.text_input("Dev execution ID", placeholder="e.g. 8098001", key="gate_exec_id")
        live_fetch = st.checkbox("Fetch latest Splunk data before scoring", value=True)

        if st.button("Score for prod risk", type="primary", disabled=not exec_id_gate.strip()):
            with st.spinner("Fetching Splunk data and scoring…"):
                try:
                    from agent.orchestrator import score_dev_execution

                    report = score_dev_execution(exec_id_gate.strip(), live=live_fetch)
                    combined = report.combined or report.structured
                    rec = report.recommendation

                    st.markdown("### Combined recommendation")
                    if combined.risk == "High":
                        st.error(f"**DO NOT PROMOTE** — {rec}")
                    elif combined.risk == "Medium":
                        st.warning(f"**CAUTION** — {rec}")
                    else:
                        st.success(f"**OK TO PROMOTE** — {rec}")

                    if report.combination_note:
                        st.caption(report.combination_note)
                    if report.vector and not report.agreement:
                        st.warning("Track A and Track B disagree — review both before promoting.")

                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        _render_track_score("Track A — Transfer stats", report.structured, config.TRACK_A_WEIGHT)
                    with col_b:
                        _render_track_score("Track B — Vector similarity", report.vector, config.TRACK_B_WEIGHT)
                    with col_c:
                        _render_track_score("Combined", combined)

                    with st.expander("Full report"):
                        st.markdown(report.markdown)

                    report_path = config.REPORTS_DIR / f"risk_{exec_id_gate.strip()}.json"
                    if report_path.exists():
                        with st.expander("Raw JSON"):
                            st.json(json.loads(report_path.read_text()))
                except Exception as ex:
                    st.error(f"Error: {ex}")

    with tab1:
        st.subheader("Splunk exports")
        df, dev, prod, err = load_pipeline_data()
        if err:
            st.error(err)
            st.info("Fetch from Splunk API or copy CSVs to `data/splunk_exports/`")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Total executions", len(df))
            c2.metric("Dev pipeline", len(dev))
            c3.metric("Prod pipeline", len(prod))

        if st.button("Fetch from Splunk API (dev + prod)"):
            with st.spinner("Querying Splunk (may take 1–3 min)…"):
                try:
                    from connectors.splunk_api import fetch_all_pipelines, save_pipelines_csv

                    fetched = fetch_all_pipelines()
                    path = save_pipelines_csv(fetched)
                    st.success(f"Saved {len(fetched)} rows → {path}")
                    load_pipeline_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))

        if not dev.empty:
            st.markdown("### Dev pipeline")
            st.dataframe(
                dev[["executionId", "Status", "pipelineName", "Deploy Start Time", "Duration (Min)"]],
                use_container_width=True,
            )
        if not prod.empty:
            st.markdown("### Prod pipeline")
            st.dataframe(
                prod[["executionId", "Status", "pipelineName", "Deploy Start Time", "Duration (Min)"]],
                use_container_width=True,
            )

    with tab2:
        st.subheader("Azure log archive")
        st.caption(
            f"Dir: `{archive_dir()}` · paths: "
            "`build_debug_logs_{{eid}}/build.log`, `securityTests.log`, `deploy/deploy.log`, `load-test.log`"
        )

        archived = list_archived()
        if archived:
            display_cols = [
                "execution_id", "file_count", "build", "securityTest", "deploy", "loadTest", "total_bytes"
            ]
            st.dataframe(pd.DataFrame(archived)[display_cols], use_container_width=True)
            only_security = sum(
                1 for r in archived
                if r.get("securityTest") == "✓"
                and r.get("build") == "—"
                and r.get("deploy") == "—"
            )
            if only_security:
                st.warning(
                    f"{only_security} executions have only securityTest logs. "
                    "Re-archive with **Force re-download** to fetch build/deploy using corrected paths."
                )
            c1, c2 = st.columns(2)
            c1.metric("Archived executions", len(archived))
            c2.metric("Total log files", sum(r["file_count"] for r in archived))
        else:
            st.info("No archived logs yet.")

        col1, col2, col3 = st.columns(3)
        pipe_filter = col1.selectbox("Pipeline", ["all", "dev", "prod"])
        limit = col2.number_input("Limit (0 = all)", min_value=0, value=0, step=10)
        force = col3.checkbox("Force re-download", value=False)

        if st.button("Fetch & archive Azure logs"):
            if not config.AZURE_CONNECTION_STRING:
                st.error("Set AZURE_CONNECTION_STRING in .env")
            else:
                with st.spinner("Downloading logs from Azure File Share…"):
                    try:
                        m = archive_all_from_csv(
                            limit=int(limit), pipeline=pipe_filter, force=force
                        )
                        saved = sum(len(r.get("saved", [])) for r in m.get("results", []))
                        st.success(f"Processed {m['count']} executions, saved {saved} log files")
                        with st.expander("Manifest details"):
                            st.json(m)
                        st.rerun()
                    except Exception as ex:
                        st.error(str(ex))

    with tab3:
        st.subheader("Vector DB explorer (Track B)")
        st.caption(f"Chroma path: `{config.VECTOR_PERSIST_DIR}` · model: `{config.EMBEDDING_MODEL}`")

        try:
            from analysis.vector_viz import get_collection_stats, get_embeddings_2d, probe_query

            stats = get_collection_stats()
            if not stats.get("available"):
                st.warning(stats.get("message", "Vector index not built"))
                st.code("pip install -r requirements-vector.txt\npython3 cli.py build")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Chunks", stats["count"])
                c2.metric("Executions", stats["unique_executions"])
                c3.metric("Prod-fail chunks", stats["prod_failed_chunks"])
                c4.metric("By step", len(stats.get("by_step", {})))

                if stats.get("by_step"):
                    st.bar_chart(pd.Series(stats["by_step"]))

                emb = get_embeddings_2d(limit=400)
                if emb.get("points"):
                    pts = pd.DataFrame(emb["points"])
                    try:
                        import plotly.express as px

                        fig = px.scatter(
                            pts,
                            x="x",
                            y="y",
                            color=pts["prod_failed"].map({True: "prod_failed", False: "ok"}),
                            hover_data=["execution_id", "status"],
                            title="Log chunk embeddings (PCA 2D)",
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    except ImportError:
                        st.scatter_chart(pts, x="x", y="y", color="prod_failed")
                elif emb.get("message"):
                    st.caption(emb["message"])

                st.markdown("### Sample chunks")
                if stats.get("sample_rows"):
                    st.dataframe(pd.DataFrame(stats["sample_rows"]), use_container_width=True)

                st.markdown("### Probe similarity")
                query = st.text_area(
                    "Query text (log line or error snippet)",
                    placeholder="npm ERR! security vulnerability found",
                )
                top_k = st.slider("Top K neighbors", 3, 20, 8)
                if st.button("Search vector DB", disabled=not query.strip()):
                    hits = probe_query(query.strip(), top_k=top_k)
                    if hits:
                        st.dataframe(pd.DataFrame(hits), use_container_width=True)
                    else:
                        st.info("No results — build index first: `python3 cli.py build`")
        except ImportError as ex:
            st.error(f"Vector deps missing: {ex}")
            st.code("pip install -r requirements-vector.txt")

    with tab4:
        st.subheader("Build index & score")
        c1, c2, c3 = st.columns(3)
        if c1.button("Build dual-track (A + B)"):
            with st.spinner("Building pairs, stats, and vector index…"):
                r = subprocess.run(
                    [sys.executable, str(ROOT / "cli.py"), "build"],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                )
                st.code(r.stdout + r.stderr)
        if c2.button("Track A only (no vector)"):
            r = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), "index", "--rebuild", "--no-vector"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout + r.stderr)
        if c3.button("History report"):
            r = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), "history"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout)

        exec_id = st.text_input("Dev execution ID to score", value="8098001")
        if st.button("Score via CLI"):
            r = subprocess.run(
                [sys.executable, str(ROOT / "cli.py"), "score", "--dev-exec", exec_id],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.markdown(r.stdout or r.stderr)
            report = config.REPORTS_DIR / f"risk_{exec_id}.json"
            if report.exists():
                st.json(json.loads(report.read_text()))

    with tab5:
        st.markdown("""
## How to run

```bash
cd ~/Projects/pipeline-risk-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-vector.txt   # Track B
cp .env.example .env
```

### CLI workflow
```bash
python3 cli.py fetch-splunk
python3 cli.py archive-azure --pipeline all --force   # re-fetch all log types
python3 cli.py build                                  # Track A + Track B
python3 cli.py score --dev-exec 8098001
python3 cli.py verify azure --exec 8098001            # test all 4 log paths
```

### Dashboard
```bash
streamlit run dashboard/app.py
```

Azure log paths (per execution share):
- `build_debug_logs_{executionId}/build.log`
- `securityTests.log`
- `deploy/deploy.log`
- `load-test.log`
        """)


if __name__ == "__main__":
    main()
