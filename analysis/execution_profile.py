"""Build per-execution profile for indexing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional  # noqa: F401

import pandas as pd

import config
from connectors import azure_logs, commit_resolver, git_connector, git_local, splunk_csv
from parsers.log_parser import parse_log

_commit_correlation_cache: Optional[Dict] = None


def _correlate_commit(eid: str, deploy_start: str) -> Optional[str]:
    global _commit_correlation_cache
    if _commit_correlation_cache is None:
        try:
            pipelines = splunk_csv.load_pipelines()
            rows = pipelines.to_dict("records")
            for r in rows:
                r["executionId"] = str(r.get("executionId", ""))
            _commit_correlation_cache = git_connector.correlate_executions_to_commits(rows)
        except Exception:
            _commit_correlation_cache = {}
    hit = _commit_correlation_cache.get(eid)
    return hit.get("sha") if hit else None


def build_profile(
    row: pd.Series,
    share_names: Dict[str, str],
    failed_steps: Dict[str, str],
) -> Dict[str, Any]:
    eid = str(row["executionId"])
    share = share_names.get(eid, "")
    step = failed_steps.get(eid) or "build"
    deploy_start = row.get("Deploy Start Time", "")

    log_text = ""
    signals: List[str] = []
    if share:
        log_text = azure_logs.load_all_logs_for_execution(
            eid, share, deploy_start=str(deploy_start)
        )
        if log_text:
            parsed = parse_log(log_text, step)
            signals = parsed.signals

    commit = None
    if share:
        commit = commit_resolver.resolve_for_execution(eid, share, str(deploy_start))
    if not commit:
        commit = _correlate_commit(eid, str(deploy_start))
    git_info = git_local.analyze_commit(commit) if commit else {}

    return {
        "execution_id": eid,
        "pipeline_id": int(row["pipelineId"]),
        "status": str(row["Status"]),
        "failed_step": failed_steps.get(eid),
        "share_name": share,
        "log_signals": signals,
        "commit_sha": commit,
        "modules": git_info.get("modules", []),
        "flags": git_info.get("flags", []),
        "deploy_start": str(deploy_start),
    }
