"""Aggregate transfer statistics from pairs."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List

import config
from analysis.pair_builder import load_pairs
from models.schemas import DevProdPair


def compute_stats(pairs: List[DevProdPair]) -> Dict[str, Any]:
    dev_pass = [p for p in pairs if p.dev_status in config.FINISHED_STATUSES]
    dppf = [p for p in dev_pass if p.prod_failed_after_dev_pass]

    baseline = len(dppf) / len(dev_pass) if dev_pass else 0.0
    if len(dev_pass) < config.MIN_PAIR_SAMPLES:
        baseline = min(baseline, 0.5)  # don't over-trust tiny samples

    by_module: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    by_signal: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})

    for p in dev_pass:
        fail = p.prod_failed_after_dev_pass
        for m in p.dev_modules or ["unknown"]:
            if fail:
                by_module[m]["fail"] += 1
            else:
                by_module[m]["pass"] += 1
        for s in p.dev_log_signals or ["none"]:
            if fail:
                by_signal[s]["fail"] += 1
            else:
                by_signal[s]["pass"] += 1

    def rates(bucket: Dict[str, Dict[str, int]]) -> Dict[str, float]:
        out = {}
        for k, v in bucket.items():
            total = v["pass"] + v["fail"]
            if total >= config.MIN_PAIR_SAMPLES:
                out[k] = v["fail"] / total
        return out

    return {
        "n_pairs": len(pairs),
        "n_dev_pass": len(dev_pass),
        "n_dev_pass_prod_fail": len(dppf),
        "baseline_p_prod_fail_given_dev_pass": round(baseline, 4),
        "by_module": rates(by_module),
        "by_signal": rates(by_signal),
    }


def save_stats(stats: Dict[str, Any]) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    config.STATS_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def load_stats() -> Dict[str, Any]:
    if not config.STATS_FILE.exists():
        return {}
    return json.loads(config.STATS_FILE.read_text(encoding="utf-8"))
