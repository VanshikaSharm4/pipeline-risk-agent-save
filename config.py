"""Configuration from environment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


PROGRAM_ID = _int("PROGRAM_ID", 19905)
PIPELINE_ID_PROD = _int("PIPELINE_ID_PROD", 2357452)
PIPELINE_ID_DEV = _int("PIPELINE_ID_DEV", 47202398)

# 0 = trust Splunk CSV export as-is (no extra date filter). Set 30 to trim by age from today.
HISTORY_WINDOW_DAYS = _int("HISTORY_WINDOW_DAYS", 0)
SKIP_AZURE_LIVE = _bool("SKIP_AZURE_LIVE", True)
AZURE_LOG_MAX_AGE_DAYS = _int("AZURE_LOG_MAX_AGE_DAYS", 15)
MIN_PAIR_SAMPLES = _int("MIN_PAIR_SAMPLES", 3)

SPLUNK_PIPELINES_CSV = ROOT / os.getenv("SPLUNK_PIPELINES_CSV", "data/splunk_exports/pipelines-list.csv")
SPLUNK_FAILED_STEPS_CSV = ROOT / os.getenv("SPLUNK_FAILED_STEPS_CSV", "data/splunk_exports/first-failed-steps.csv")
SPLUNK_SHARE_NAMES_CSV = ROOT / os.getenv("SPLUNK_SHARE_NAMES_CSV", "data/splunk_exports/share-names.csv")

AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING", "")
_archive = os.getenv("LOG_ARCHIVE_DIR", "").strip() or "data/log_archive"
LOG_ARCHIVE_DIR = (ROOT / _archive).resolve() if not os.path.isabs(_archive) else Path(_archive).expanduser()

GIT_LOCAL_DIR = Path(os.getenv("GIT_LOCAL_DIR", "")).expanduser() if os.getenv("GIT_LOCAL_DIR", "").strip() else None

INDEX_DIR = ROOT / os.getenv("INDEX_DIR", "data/index")
VECTOR_PERSIST_DIR = ROOT / os.getenv("VECTOR_PERSIST_DIR", "data/index/vector_store")
LOG_CACHE_DIR = ROOT / os.getenv("LOG_CACHE_DIR", "data/log_cache")
REPORTS_DIR = ROOT / "reports"

ENABLE_VECTOR_TRACK = _bool("ENABLE_VECTOR_TRACK", False)
VECTOR_TOP_K = _int("VECTOR_TOP_K", 8)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

PAIRS_FILE = INDEX_DIR / "dev_prod_pairs.json"
STATS_FILE = INDEX_DIR / "transfer_stats.json"
BACKTEST_FILE = INDEX_DIR / "backtest_results.json"

FINISHED_STATUSES = frozenset({"FINISHED", "SUCCESS"})
FAILED_STATUSES = frozenset({"FAILED", "ERROR", "CANCELLED"})
