"""Scan existing Azure log archive and map to Splunk executions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import config
from connectors import splunk_csv


def scan_archive() -> Dict[str, Any]:
    base = config.LOG_ARCHIVE_DIR
    if not base or not base.is_dir():
        return {"error": f"Archive dir missing: {base}", "executions": []}

    pipelines = splunk_csv.load_pipelines()
    shares = splunk_csv.load_share_names()
    known_eids = set(pipelines["executionId"].astype(str))

    by_eid: Dict[str, List[str]] = {}
    by_share: Dict[str, List[str]] = {}

    for path in base.rglob("*.log"):
        rel = str(path.relative_to(base))
        parts = path.relative_to(base).parts
        if parts and parts[0].isdigit():
            by_eid.setdefault(parts[0], []).append(rel)
        elif len(parts) >= 1:
            by_share.setdefault(parts[0], []).append(rel)

    matched = []
    unmatched_dirs = []
    for eid in known_eids:
        files = by_eid.get(eid, [])
        if not files:
            share = shares.get(eid, "")
            if share and share in by_share:
                files = by_share[share]
        matched.append({
            "execution_id": eid,
            "log_files": files,
            "has_logs": len(files) > 0,
        })

    for d in base.iterdir():
        if d.is_dir() and d.name not in known_eids and d.name not in shares.values():
            logs = list(d.rglob("*.log"))
            if logs:
                unmatched_dirs.append({"dir": d.name, "log_count": len(logs)})

    with_logs = sum(1 for m in matched if m["has_logs"])
    return {
        "archive_dir": str(base),
        "total_executions_in_csv": len(known_eids),
        "executions_with_logs": with_logs,
        "coverage_pct": round(100 * with_logs / max(len(known_eids), 1), 1),
        "unmatched_archive_dirs": unmatched_dirs[:20],
        "executions": [m for m in matched if m["has_logs"]],
    }
