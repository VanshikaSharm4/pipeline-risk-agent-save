"""Download Azure logs into permanent archive before 15-day purge."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import config
from connectors import azure_logs, splunk_csv

STEPS = ("build", "securityTest", "deploy", "loadTest")


def archive_dir() -> Path:
    d = config.LOG_ARCHIVE_DIR or (config.ROOT / "data" / "log_archive")
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_path(execution_id: str, step: str) -> Path:
    """Store under execution_id/ using simple names (build.log, deploy/deploy.log)."""
    fname = azure_logs.ARCHIVE_FILENAMES.get(step, "build.log")
    if step == "deploy":
        p = archive_dir() / execution_id / "deploy"
        p.mkdir(parents=True, exist_ok=True)
        return p / "deploy.log"
    if step in ("build", "codeQuality"):
        p = archive_dir() / execution_id / f"build_debug_logs_{execution_id}"
        p.mkdir(parents=True, exist_ok=True)
        return p / "build.log"
    p = archive_dir() / execution_id
    p.mkdir(parents=True, exist_ok=True)
    return p / fname


def _log_types_from_files(files: List[str]) -> Dict[str, bool]:
    joined = " ".join(files).lower()
    return {
        "build": "build.log" in joined,
        "securityTest": "securitytests" in joined or "securitytest" in joined,
        "deploy": "deploy.log" in joined or "/deploy/" in joined,
        "loadTest": "load-test" in joined or "loadtest" in joined,
    }


def list_archived() -> List[Dict[str, Any]]:
    base = archive_dir()
    rows = []
    if not base.is_dir():
        return rows
    for eid_dir in sorted(base.iterdir()):
        if not eid_dir.is_dir() or eid_dir.name.startswith("."):
            continue
        if eid_dir.name == "manifest.json":
            continue
        files = list(eid_dir.rglob("*.log"))
        rel_files = [str(f.relative_to(base)) for f in files]
        types = _log_types_from_files(rel_files)
        rows.append({
            "execution_id": eid_dir.name,
            "file_count": len(files),
            "total_bytes": sum(f.stat().st_size for f in files),
            "build": "✓" if types["build"] else "—",
            "securityTest": "✓" if types["securityTest"] else "—",
            "deploy": "✓" if types["deploy"] else "—",
            "loadTest": "✓" if types["loadTest"] else "—",
            "files": rel_files,
        })
    return rows


def archive_execution(
    execution_id: str,
    share_name: str,
    deploy_start: str = "",
    *,
    force: bool = False,
) -> Dict[str, Any]:
    saved = []
    skipped = []
    errors = []

    for step in STEPS:
        dest = archive_path(execution_id, step)
        if dest.is_file() and dest.stat().st_size > 0 and not force:
            skipped.append(str(dest.relative_to(archive_dir())))
            continue

        text = azure_logs.fetch_live(share_name, step, execution_id) if config.AZURE_CONNECTION_STRING else ""
        if not text or text.startswith("ERROR:"):
            errors.append(f"{step}: {text or 'no azure creds'}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        saved.append(str(dest.relative_to(archive_dir())))

    return {"execution_id": execution_id, "saved": saved, "skipped": skipped, "errors": errors}


def archive_all_from_csv(
    limit: int = 0,
    *,
    force: bool = False,
    pipeline: str = "all",
) -> Dict[str, Any]:
    """Archive logs for executions in Splunk CSV."""
    if not config.AZURE_CONNECTION_STRING:
        raise ValueError("Set AZURE_CONNECTION_STRING in .env to fetch Azure logs")

    df = splunk_csv.load_pipelines()
    shares = splunk_csv.load_share_names()
    dev, prod = splunk_csv.split_dev_prod(df)
    if pipeline == "dev":
        target = dev
    elif pipeline == "prod":
        target = prod
    else:
        target = df

    results = []
    for i, (_, row) in enumerate(target.iterrows()):
        if limit and i >= limit:
            break
        eid = str(row["executionId"])
        share = shares.get(eid)
        if not share:
            results.append({"execution_id": eid, "errors": ["no share name in CSV"]})
            continue
        results.append(
            archive_execution(
                eid, share, str(row.get("Deploy Start Time", "")), force=force
            )
        )

    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_filter": pipeline,
        "count": len(results),
        "results": results,
    }
    manifest_path = archive_dir() / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
