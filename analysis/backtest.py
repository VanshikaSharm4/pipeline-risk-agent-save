"""Backtest Track A on historical dev_pass pairs."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import config
from agent.rule_engine import score_structured
from analysis.pair_builder import load_pairs


def run_backtest() -> Dict[str, Any]:
    pairs = load_pairs()
    dev_pass = [p for p in pairs if p.dev_status in config.FINISHED_STATUSES]
    results = []
    correct_high = 0
    total_high = 0
    false_comfort = 0

    for p in dev_pass:
        profile = {
            "status": p.dev_status,
            "modules": p.dev_modules,
            "log_signals": p.dev_log_signals,
            "flags": [],
        }
        score = score_structured(profile)
        actual_fail = p.prod_failed_after_dev_pass
        pred_high = score.risk == "High"
        if pred_high:
            total_high += 1
            if actual_fail:
                correct_high += 1
        if score.risk == "Low" and actual_fail:
            false_comfort += 1

        results.append({
            "dev_execution_id": p.dev_execution_id,
            "predicted_risk": score.risk,
            "prob": score.prob,
            "actual_prod_fail": actual_fail,
        })

    precision = correct_high / total_high if total_high else 0.0
    summary = {
        "n_scored": len(results),
        "precision_at_high": round(precision, 4),
        "false_comfort_count": false_comfort,
        "results": results,
    }
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    config.BACKTEST_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
