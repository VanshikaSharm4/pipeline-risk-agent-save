"""Build Track A (pairs/stats) + Track B (vector) from Splunk CSV + Azure archive."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import config
from analysis import vector_index
from analysis.execution_profile import build_profile
from analysis.pair_builder import build_pairs, save_pairs
from analysis.transfer_stats import compute_stats, save_stats
from connectors import azure_archive_scan, azure_logs, splunk_csv
from parsers.log_parser import parse_log


def build_track_a() -> Tuple[List, Dict[str, Any]]:
    pairs = build_pairs()
    save_pairs(pairs)
    stats = compute_stats(pairs)
    save_stats(stats)
    return pairs, stats


def build_track_b() -> Dict[str, Any]:
    if not config.ENABLE_VECTOR_TRACK:
        return {"enabled": False, "chunks": 0, "reason": "ENABLE_VECTOR_TRACK=false"}

    if not vector_index._vector_available():
        return {
            "enabled": False,
            "chunks": 0,
            "reason": "pip install -r requirements-vector.txt",
        }

    pipelines = splunk_csv.load_pipelines()
    failed_df = splunk_csv.load_failed_steps()
    failed_map = dict(zip(failed_df["executionId"], failed_df.get("firstFailedStep", "")))
    shares = splunk_csv.load_share_names()

    profiles: List[Dict[str, Any]] = []
    skipped = 0
    for _, row in pipelines.iterrows():
        eid = str(row["executionId"])
        share = shares.get(eid, "")
        prof = build_profile(row, shares, failed_map)
        if share:
            full_log = azure_logs.load_all_logs_for_execution(
                eid, share, str(row.get("Deploy Start Time", ""))
            )
            if full_log:
                prof["_log_text"] = full_log
                parsed = parse_log(full_log)
                prof["log_signals"] = list(set(prof.get("log_signals", []) + parsed.signals))
            else:
                skipped += 1
        else:
            skipped += 1
        profiles.append(prof)

    chunks = vector_index.build_index(profiles)
    return {
        "enabled": True,
        "chunks": chunks,
        "profiles_indexed": len(profiles),
        "skipped_no_logs": skipped,
    }


def build_dual_track() -> Dict[str, Any]:
    scan = azure_archive_scan.scan_archive()
    pairs, stats = build_track_a()
    vector = build_track_b()
    return {
        "archive_scan": {
            "dir": scan.get("archive_dir"),
            "coverage_pct": scan.get("coverage_pct"),
            "executions_with_logs": scan.get("executions_with_logs"),
        },
        "track_a": {
            "pairs": len(pairs),
            "baseline_p_prod_fail_given_dev_pass": stats.get(
                "baseline_p_prod_fail_given_dev_pass", 0
            ),
            "n_dev_pass_prod_fail": stats.get("n_dev_pass_prod_fail", 0),
        },
        "track_b": vector,
    }
