"""Build dev→prod pairs by commit SHA, with time-based fallback."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

import config
from analysis.execution_profile import build_profile
from connectors import splunk_csv
from models.schemas import DevProdPair


def _parse_time(s: str) -> pd.Timestamp:
    raw = str(s).strip()
    if raw:
        raw = pd.Series([raw]).str.replace(r"\s+[A-Z]{2,4}$", "", regex=True)[0]
    return pd.to_datetime(raw, errors="coerce", utc=True)


def _pick_prod_after_dev(
    dev: Dict[str, Any], prod_list: List[Dict[str, Any]], window: timedelta
) -> Optional[Dict[str, Any]]:
    dev_end = _parse_time(dev.get("deploy_start", ""))
    if pd.isna(dev_end):
        return None
    best = None
    best_start = None
    for prod in prod_list:
        prod_start = _parse_time(prod.get("deploy_start", ""))
        if pd.isna(prod_start) or prod_start < dev_end:
            continue
        if (prod_start - dev_end) > window:
            continue
        if best is None or prod_start < best_start:
            best = prod
            best_start = prod_start
    return best


def _append_pair(
    pairs: List[DevProdPair],
    dev: Dict[str, Any],
    prod: Dict[str, Any],
    sha: str,
    confidence: str,
) -> None:
    dev_pass = dev["status"] in config.FINISHED_STATUSES
    prod_fail = prod["status"] in config.FAILED_STATUSES
    label = "dev_pass_prod_fail" if dev_pass and prod_fail else (
        "dev_pass_prod_pass" if dev_pass and prod["status"] in config.FINISHED_STATUSES
        else "other"
    )
    pairs.append(
        DevProdPair(
            commit_sha=sha or "",
            dev_execution_id=dev["execution_id"],
            dev_status=dev["status"],
            dev_failed_step=dev.get("failed_step"),
            dev_log_signals=dev.get("log_signals", []),
            dev_modules=dev.get("modules", []),
            prod_execution_id=prod["execution_id"],
            prod_status=prod["status"],
            prod_failed_step=prod.get("failed_step"),
            prod_log_signals=prod.get("log_signals", []),
            label=label,
            pair_confidence=confidence,
            prod_failed_after_dev_pass=dev_pass and prod_fail,
        )
    )


def build_pairs() -> List[DevProdPair]:
    pipelines = splunk_csv.load_pipelines()
    failed_df = splunk_csv.load_failed_steps()
    failed_map = dict(zip(failed_df["executionId"], failed_df.get("firstFailedStep", "")))
    shares = splunk_csv.load_share_names()
    dev_df, prod_df = splunk_csv.split_dev_prod(pipelines)

    dev_profiles = [build_profile(row, shares, failed_map) for _, row in dev_df.iterrows()]
    prod_profiles = [build_profile(row, shares, failed_map) for _, row in prod_df.iterrows()]

    pairs: List[DevProdPair] = []
    window = timedelta(days=14)
    paired_dev_ids = set()

    dev_by_commit: Dict[str, List[Dict[str, Any]]] = {}
    prod_by_commit: Dict[str, List[Dict[str, Any]]] = {}
    for dev in dev_profiles:
        sha = dev.get("commit_sha")
        if sha:
            dev_by_commit.setdefault(sha, []).append(dev)
    for prod in prod_profiles:
        sha = prod.get("commit_sha")
        if sha:
            prod_by_commit.setdefault(sha, []).append(prod)

    for sha, dev_list in dev_by_commit.items():
        prod_list = prod_by_commit.get(sha, [])
        if not prod_list:
            continue
        for dev in dev_list:
            best_prod = _pick_prod_after_dev(dev, prod_list, window)
            if best_prod:
                _append_pair(pairs, dev, best_prod, sha, "high")
                paired_dev_ids.add(dev["execution_id"])

    for dev in dev_profiles:
        if dev["execution_id"] in paired_dev_ids:
            continue
        if dev["status"] not in config.FINISHED_STATUSES:
            continue
        best_prod = _pick_prod_after_dev(dev, prod_profiles, window)
        if best_prod:
            _append_pair(pairs, dev, best_prod, "", "low")
            paired_dev_ids.add(dev["execution_id"])

    return pairs


def save_pairs(pairs: List[DevProdPair]) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    data = [p.model_dump() for p in pairs]
    config.PAIRS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_pairs() -> List[DevProdPair]:
    if not config.PAIRS_FILE.exists():
        return []
    raw = json.loads(config.PAIRS_FILE.read_text(encoding="utf-8"))
    return [DevProdPair.model_validate(x) for x in raw]
