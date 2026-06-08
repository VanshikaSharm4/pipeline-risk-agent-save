"""Azure File Share log fetch + local archive.

Cloud Manager layout (per share UUID):
  build_debug_logs_{executionId}/build.log
  securityTests.log
  deploy/deploy.log
  load-test.log
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import config

# Canonical paths — execution_id required for build logs
STEP_PATH_TEMPLATES = {
    "build": ["build_debug_logs_{eid}/build.log", "build.log"],
    "codeQuality": ["build_debug_logs_{eid}/build.log", "build.log"],
    "securityTest": ["securityTests.log", "securityTest.log"],
    "deploy": ["deploy/deploy.log", "deploy.log"],
    "loadTest": ["load-test.log", "loadTest.log"],
}

ARCHIVE_FILENAMES = {
    "build": "build.log",
    "codeQuality": "build.log",
    "securityTest": "securityTests.log",
    "deploy": "deploy.log",
    "loadTest": "load-test.log",
}

# Back-compat alias used by archiver
LOG_MAP = {
    "build": "build_debug_logs_{eid}/build.log",
    "codeQuality": "build_debug_logs_{eid}/build.log",
    "securityTest": "securityTests.log",
    "deploy": "deploy/deploy.log",
    "loadTest": "load-test.log",
}


def live_paths_for_step(execution_id: str, step: str) -> List[str]:
    templates = STEP_PATH_TEMPLATES.get(step, ["build.log"])
    return [t.replace("{eid}", execution_id) for t in templates]


def _cache_path(share_name: str, step: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", share_name)[:64]
    return config.LOG_CACHE_DIR / f"{safe}_{step}.log"


def _archive_paths(execution_id: str, share_name: str, step: str) -> List[Path]:
    if not config.LOG_ARCHIVE_DIR:
        return []
    fname = ARCHIVE_FILENAMES.get(step, "build.log")
    base = config.LOG_ARCHIVE_DIR
    paths = [
        base / execution_id / fname,
        base / execution_id / "build_debug_logs" / fname,
        base / execution_id / "deploy" / fname,
        base / share_name / fname,
        base / share_name / "deploy" / fname,
        base / share_name / f"build_debug_logs_{execution_id}" / "build.log",
    ]
    if step in ("build", "codeQuality"):
        paths.insert(0, base / execution_id / f"build_debug_logs_{execution_id}" / "build.log")
    return paths


def read_from_archive(execution_id: str, share_name: str, step: str) -> Optional[str]:
    for p in _archive_paths(execution_id, share_name, step):
        if p.is_file() and p.stat().st_size > 0:
            return p.read_text(encoding="utf-8", errors="replace")
    return None


def list_share_files(share_name: str, prefix: str = "") -> List[str]:
    """List files in Azure share (for path discovery)."""
    if not config.AZURE_CONNECTION_STRING:
        return []
    try:
        from azure.storage.fileshare import ShareClient

        client = ShareClient.from_connection_string(
            conn_str=config.AZURE_CONNECTION_STRING,
            share_name=share_name,
        )
        dir_client = client.get_directory_client(prefix)
        out = []
        for item in dir_client.list_directories_and_files():
            name = item["name"]
            if item["is_directory"]:
                out.extend(list_share_files(share_name, f"{prefix}{name}/" if prefix else f"{name}/"))
            else:
                out.append(f"{prefix}{name}" if prefix else name)
        return out
    except Exception:
        return []


def discover_log_paths(share_name: str, execution_id: str) -> dict[str, str]:
    """Find actual log paths by listing share + known templates."""
    found: dict[str, str] = {}
    for step in ("build", "securityTest", "deploy", "loadTest"):
        for path in live_paths_for_step(execution_id, step):
            if _fetch_path(share_name, path):
                found[step] = path
                break
    if not found:
        all_files = list_share_files(share_name)
        for f in all_files:
            fl = f.lower()
            if "build.log" in fl and "build" not in found:
                found["build"] = f
            if "securitytests.log" in fl or "securitytest" in fl:
                found["securityTest"] = f
            if "deploy.log" in fl and "deploy" not in found:
                found["deploy"] = f
            if "load-test" in fl or "loadtest" in fl:
                found["loadTest"] = f
    return found


def _fetch_path(share_name: str, file_path: str) -> Optional[str]:
    if not config.AZURE_CONNECTION_STRING:
        return None
    try:
        from azure.storage.fileshare import ShareFileClient

        client = ShareFileClient.from_connection_string(
            conn_str=config.AZURE_CONNECTION_STRING,
            share_name=share_name,
            file_path=file_path,
        )
        return client.download_file().readall().decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_live(share_name: str, step: str, execution_id: str = "") -> str:
    if not config.AZURE_CONNECTION_STRING:
        return ""
    eid = execution_id or ""
    for path in live_paths_for_step(eid, step) if eid else STEP_PATH_TEMPLATES.get(step, ["build.log"]):
        text = _fetch_path(share_name, path.replace("{eid}", eid) if "{eid}" in path else path)
        if text:
            return text
    if eid:
        discovered = discover_log_paths(share_name, eid)
        if step in discovered:
            text = _fetch_path(share_name, discovered[step])
            if text:
                return text
    return f"ERROR: no log found for step={step} share={share_name[:12]}... eid={execution_id}"


def execution_age_days(deploy_start: str) -> Optional[float]:
    try:
        import pandas as pd
        raw = str(deploy_start).strip()
        raw = pd.Series([raw]).str.replace(r"\s+[A-Z]{2,4}$", "", regex=True)[0]
        ts = pd.to_datetime(raw, errors="coerce", utc=True)
        if pd.isna(ts):
            return None
        return (datetime.now(timezone.utc) - ts.to_pydatetime()).total_seconds() / 86400
    except Exception:
        return None


def get_log(
    execution_id: str,
    share_name: str,
    step: str,
    deploy_start: Optional[str] = None,
    *,
    allow_live: bool = True,
) -> str:
    archived = read_from_archive(execution_id, share_name, step)
    if archived:
        return archived

    cache = _cache_path(share_name, step)
    if cache.is_file() and cache.stat().st_size > 0:
        return cache.read_text(encoding="utf-8", errors="replace")

    if allow_live and deploy_start:
        age = execution_age_days(deploy_start)
        if age is not None and age > config.AZURE_LOG_MAX_AGE_DAYS:
            return ""

    if config.SKIP_AZURE_LIVE:
        return ""

    if allow_live and config.AZURE_CONNECTION_STRING:
        text = fetch_live(share_name, step, execution_id)
        if text and not text.startswith("ERROR:"):
            config.LOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
            return text
        return text if text else ""

    return ""


def load_all_logs_for_execution(
    execution_id: str,
    share_name: str,
    deploy_start: Optional[str] = None,
    *,
    steps: tuple = ("build", "securityTest", "deploy", "loadTest"),
) -> str:
    parts = []
    for step in steps:
        text = get_log(
            execution_id,
            share_name,
            step,
            deploy_start=deploy_start,
            allow_live=not config.SKIP_AZURE_LIVE,
        )
        if text and not text.startswith("ERROR:"):
            parts.append(f"=== {step} ===\n{text}")
    return "\n\n".join(parts)
