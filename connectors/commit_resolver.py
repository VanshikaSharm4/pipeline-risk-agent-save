"""Resolve executionId → git commit SHA from build.log."""

from __future__ import annotations

import re
from typing import Optional

from connectors import azure_logs

COMMIT_PATTERNS = [
    re.compile(r"(?:commit|Commit|GIT_COMMIT|git\.commit)[:\s=]+([0-9a-f]{7,40})", re.I),
    re.compile(r"Checking out revision\s+([0-9a-f]{7,40})", re.I),
    re.compile(r"revision\s+([0-9a-f]{7,40})", re.I),
]


def resolve_from_log(log_text: str) -> Optional[str]:
    if not log_text or log_text.startswith("ERROR:"):
        return None
    for pat in COMMIT_PATTERNS:
        m = pat.search(log_text)
        if m:
            return m.group(1)[:40]
    return None


def resolve_for_execution(
    execution_id: str,
    share_name: str,
    deploy_start: Optional[str] = None,
) -> Optional[str]:
    log = azure_logs.get_log(
        execution_id, share_name, "build", deploy_start=deploy_start
    )
    return resolve_from_log(log)
