"""
Adobe Cloud Manager Git connector (from devops-agent-2 patterns).
Clones locally; credentials in .env only — never sent to cloud LLM.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

MAX_DIFF_BYTES = 500_000
_GIT_FETCH_TTL_MIN = int(os.getenv("GIT_FETCH_TTL_MINUTES", "10"))
_last_fetch_ts: float = 0.0


def _repo_url() -> str:
    url = os.getenv("CM_GIT_REPO_URL", "")
    if not url:
        raise ValueError("CM_GIT_REPO_URL must be set in .env")
    return url


def _local_dir() -> str:
    return os.getenv("GIT_LOCAL_DIR", os.path.expanduser("~/idfc-repo"))


def _auth_url() -> str:
    username = os.getenv("CM_GIT_USERNAME", "")
    password = os.getenv("CM_GIT_PASSWORD", "")
    url = _repo_url()
    if username and password:
        return url.replace(
            "https://",
            f"https://{quote(username, safe='')}:{quote(password, safe='')}@",
        )
    return url


def _git(*args: str, cwd: Optional[str] = None) -> str:
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd or _local_dir(),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr[:500]}")
    return result.stdout


def clone_or_update() -> str:
    repo_dir = Path(_local_dir())
    if not (repo_dir / ".git").exists():
        result = subprocess.run(
            ["git", "clone", _auth_url(), str(repo_dir)],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr[:500]}")
        subprocess.run(
            ["git", "remote", "set-url", "origin", _repo_url()],
            cwd=str(repo_dir),
            capture_output=True,
        )
        return str(repo_dir)

    global _last_fetch_ts
    if (time.time() - _last_fetch_ts) / 60 < _GIT_FETCH_TTL_MIN:
        return str(repo_dir)

    try:
        auth_url = _auth_url()
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
        subprocess.run(
            ["git", "remote", "set-url", "origin", _repo_url()],
            cwd=str(repo_dir),
            capture_output=True,
        )
        subprocess.run(
            ["git", "fetch", "--prune", auth_url, "+refs/heads/*:refs/remotes/origin/*"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        branch = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        ).stdout.strip()
        if branch:
            subprocess.run(
                ["git", "merge", "--ff-only", f"refs/remotes/origin/{branch}"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        _last_fetch_ts = time.time()
    except Exception:
        _last_fetch_ts = time.time()
    return str(repo_dir)


def get_commit_diff(sha: str) -> Dict[str, Any]:
    clone_or_update()
    title = _git("log", "-1", "--format=%s", sha).strip()
    author = _git("log", "-1", "--format=%an", sha).strip()
    parents_line = _git("rev-list", "--parents", "-n", "1", sha).strip().split()
    parents = parents_line[1:] if len(parents_line) > 1 else []
    if parents:
        files_out = _git("diff", "--find-renames", "--name-only", parents[0], sha)
        diff_out = _git("diff", "--find-renames", parents[0], sha)
    else:
        files_out = _git("diff-tree", "--root", "--no-commit-id", "-r", "--name-only", sha)
        diff_out = _git("diff-tree", "--root", "--no-commit-id", "-r", "-p", sha)
    changed_files = [f.strip() for f in files_out.splitlines() if f.strip()]
    excerpt = diff_out[:MAX_DIFF_BYTES]
    return {
        "commit_sha": sha,
        "title": title,
        "author": author,
        "changed_files": changed_files,
        "diff_excerpt": excerpt,
    }


def correlate_executions_to_commits(
    execution_rows: List[Dict],
    branch: str = "master",
    time_col: str = "Deploy Start Time",
) -> Dict[str, Dict]:
    """Map executionId → commit by timestamp (when build.log has no SHA)."""
    import pandas as pd

    try:
        clone_or_update()
    except Exception:
        pass

    import datetime
    days_back = int(os.getenv("GIT_CORRELATE_DAYS", "90"))
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        out = _git("log", f"--after={since}", "--format=%H|%s|%an|%aI", branch)
    except RuntimeError:
        return {}

    commits = []
    for line in out.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({"sha": parts[0], "title": parts[1], "timestamp": parts[3]})

    _TZ_ALIASES = {
        " PDT": "-07:00", " PST": "-08:00", " MDT": "-06:00", " MST": "-07:00",
        " CDT": "-05:00", " CST": "-06:00", " EDT": "-04:00", " EST": "-05:00",
        " IST": "+05:30", " UTC": "+00:00", " GMT": "+00:00",
    }

    def norm(ts: str):
        try:
            s = str(ts).strip()
            for abbr, offset in _TZ_ALIASES.items():
                if s.endswith(abbr):
                    s = s[: -len(abbr)] + offset
                    break
            return pd.to_datetime(s, utc=True)
        except Exception:
            try:
                return pd.to_datetime(ts, infer_datetime_format=True, utc=True)
            except Exception:
                return None

    commit_utc = [norm(c["timestamp"]) for c in commits]
    result: Dict[str, Dict] = {}
    for row in execution_rows:
        eid = str(row.get("executionId", ""))
        exec_utc = norm(str(row.get(time_col, "")))
        if not eid or exec_utc is None:
            continue
        for i, c_utc in enumerate(commit_utc):
            if c_utc is not None and c_utc <= exec_utc:
                result[eid] = {"sha": commits[i]["sha"], "title": commits[i]["title"]}
                break
    return result
