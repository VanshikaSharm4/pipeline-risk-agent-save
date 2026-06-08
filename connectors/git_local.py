"""Module analysis from local CM git — uses git_connector."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from connectors import git_connector

MODULE_PATTERNS = [
    (re.compile(r"^ui\.frontend/"), "ui.frontend"),
    (re.compile(r"^dispatcher"), "dispatcher"),
    (re.compile(r"ui\.config"), "ui.config"),
    (re.compile(r"^ui\.apps/"), "ui.apps"),
    (re.compile(r"pom\.xml$"), "core"),
    (re.compile(r"package\.json$"), "ui.frontend"),
]


def analyze_commit(commit_sha: str) -> Dict[str, Any]:
    if not commit_sha:
        return {"modules": [], "changed_files": [], "lines_changed": 0, "flags": []}
    try:
        data = git_connector.get_commit_diff(commit_sha)
        files = data.get("changed_files", [])
        modules = sorted({m for f in files for rx, m in MODULE_PATTERNS if rx.search(f)})
        flags = []
        if any("dispatcher" in f or f.endswith(".conf") for f in files):
            flags.append("dispatcher_or_conf")
        if any("pom.xml" in f or "package.json" in f for f in files):
            flags.append("dependency_change")
        if any("config" in f.lower() for f in files):
            flags.append("config_change")
        return {
            "modules": modules,
            "changed_files": files[:50],
            "lines_changed": len(data.get("diff_excerpt", "")),
            "flags": flags,
        }
    except Exception:
        return {"modules": [], "changed_files": [], "lines_changed": 0, "flags": []}
