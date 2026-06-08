"""Agent loop: collect → score A/B → explain."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pandas as pd

import config
from agent.combined_scorer import combine_tracks
from agent.explainer import render_report
from agent.rule_engine import score_structured
from analysis import vector_index
from analysis.execution_profile import build_profile
from analysis.pair_builder import build_pairs
from analysis.transfer_stats import compute_stats
from connectors import splunk_csv
from models.schemas import DevProdPair, ProdRiskReport, TrackScore


def _fetch_live_pipelines() -> pd.DataFrame:
    """Pull latest dev+prod executions from Splunk API and save to CSV."""
    from connectors.splunk_api import fetch_all_pipelines, save_pipelines_csv
    df = fetch_all_pipelines()
    if not df.empty:
        save_pipelines_csv(df)
    return df


def _profile_for_dev_exec(execution_id: str, live: bool = True) -> Dict[str, Any]:
    pipelines = splunk_csv.load_pipelines()
    dev_df, _ = splunk_csv.split_dev_prod(pipelines)
    row = splunk_csv.get_execution_row(dev_df, execution_id)

    if row is None and live:
        # Not in cached CSV — try fetching live from Splunk
        try:
            pipelines = _fetch_live_pipelines()
            dev_df, _ = splunk_csv.split_dev_prod(pipelines)
            row = splunk_csv.get_execution_row(dev_df, execution_id)
        except Exception as e:
            raise ValueError(
                f"Dev execution {execution_id} not in CSV and live fetch failed: {e}"
            )

    if row is None:
        raise ValueError(
            f"Dev execution {execution_id} not found in program {config.PROGRAM_ID} "
            f"pipeline {config.PIPELINE_ID_DEV}"
        )

    failed_df = splunk_csv.load_failed_steps()
    failed_map = dict(zip(failed_df["executionId"], failed_df.get("firstFailedStep", "")))
    shares = splunk_csv.load_share_names()
    prof = build_profile(row, shares, failed_map)

    share = prof.get("share_name", "")
    step = prof.get("failed_step") or "build"
    if share:
        from connectors import azure_logs
        prof["_log_text"] = azure_logs.load_all_logs_for_execution(
            execution_id, share, deploy_start=prof.get("deploy_start")
        )
    return prof


def _live_stats() -> Dict[str, Any]:
    """Fetch fresh dev+prod data from Splunk and compute transfer stats."""
    try:
        pipelines = _fetch_live_pipelines()
        if pipelines.empty:
            return {}
        pairs = build_pairs()
        return compute_stats(pairs)
    except Exception:
        return {}


def score_dev_execution(
    execution_id: str,
    commit_override: Optional[str] = None,
    live: bool = True,
) -> ProdRiskReport:
    """Score a dev execution for prod promotion risk.

    When live=True (default) fetches the latest dev+prod data from Splunk before
    scoring so the baseline always reflects current history.
    """
    if live:
        # Refresh full history from Splunk — updates CSV and pairs index
        try:
            fresh_df = _fetch_live_pipelines()
            if not fresh_df.empty:
                pairs = build_pairs()
                stats = compute_stats(pairs)
                from analysis.transfer_stats import save_stats
                from analysis.pair_builder import save_pairs
                save_pairs(pairs)
                save_stats(stats)
        except Exception:
            pass  # Fall back to whatever is on disk

    profile = _profile_for_dev_exec(execution_id, live=live)
    if commit_override:
        profile["commit_sha"] = commit_override

    structured = score_structured(profile)

    vector_data = None
    if config.ENABLE_VECTOR_TRACK and config.VECTOR_PERSIST_DIR.exists():
        raw = vector_index.query_similar(profile.get("_log_text", ""))
        vector_data = TrackScore(
            prob=raw["prob"],
            risk=raw["risk"],
            confidence=raw["confidence"],
            drivers=raw["drivers"],
            n_samples=raw["n_samples"],
        )

    combined, combo_note = combine_tracks(structured, vector_data)
    agree = vector_data is None or structured.risk == vector_data.risk
    md = render_report(
        execution_id,
        profile.get("commit_sha"),
        structured,
        vector_data,
        combined=combined,
        combination_note=combo_note,
    )

    report = ProdRiskReport(
        dev_execution_id=execution_id,
        commit_sha=profile.get("commit_sha"),
        structured=structured,
        vector=vector_data,
        combined=combined,
        agreement=agree,
        combination_note=combo_note,
        recommendation=_rec_from_structured(combined, vector_data),
        markdown=md,
    )

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORTS_DIR / f"risk_{execution_id}.json"
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (config.REPORTS_DIR / f"risk_{execution_id}.md").write_text(md, encoding="utf-8")
    _append_prediction_log(execution_id, profile, report)
    return report


def _append_prediction_log(
    execution_id: str,
    profile: Dict[str, Any],
    report: ProdRiskReport,
) -> None:
    """Append-only log for enterprise learning loop (outcome join later)."""
    import json
    from datetime import datetime, timezone

    log_path = config.INDEX_DIR / "prediction_log.jsonl"
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "dev_execution_id": execution_id,
        "commit_sha": profile.get("commit_sha"),
        "dev_status": profile.get("status"),
        "modules": profile.get("modules", []),
        "log_signals": profile.get("log_signals", []),
        "prob_structured": report.structured.prob,
        "risk_structured": report.structured.risk,
        "prob_vector": report.vector.prob if report.vector else None,
        "risk_vector": report.vector.risk if report.vector else None,
        "prob_combined": report.combined.prob if report.combined else None,
        "risk_combined": report.combined.risk if report.combined else None,
        "recommendation": report.recommendation,
        "prod_outcome": None,
        "prod_execution_id": None,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _rec_from_structured(s: TrackScore, v: Optional[TrackScore]) -> str:
    from agent.explainer import _recommendation
    return _recommendation(s, v)
