"""Track A — structured scoring from rules + transfer stats."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import config
from analysis.pair_builder import load_pairs
from analysis.transfer_stats import load_stats
from models.schemas import TrackScore
from parsers.log_parser import INFRA_SIGNALS


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0


def score_structured(profile: Dict[str, Any]) -> TrackScore:
    stats = load_stats()
    pairs = load_pairs()
    drivers: List[str] = []
    n_dev_pass = stats.get("n_dev_pass", 0)
    prob = stats.get("baseline_p_prod_fail_given_dev_pass", 0.3)
    if n_dev_pass < config.MIN_PAIR_SAMPLES:
        prob = 0.3
        drivers.append(
            f"[STATS] only {n_dev_pass} dev_pass pairs in index — using default 30%"
        )

    status = profile.get("status", "")
    if status in config.FAILED_STATUSES:
        return TrackScore(
            prob=0.95,
            risk="High",
            confidence="high",
            drivers=["[RULE] Dev execution failed — do not promote"],
            n_samples=0,
        )

    modules = profile.get("modules", [])
    signals = [s for s in profile.get("log_signals", []) if s not in INFRA_SIGNALS]
    flags = profile.get("flags", [])

    if "dispatcher_or_conf" in flags:
        prob += 0.2
        drivers.append("[RULE-DEPLOY-03] dispatcher or conf changed (+0.20)")

    if "dependency_change" in flags:
        prob += 0.15
        drivers.append("[RULE-BUILD-01] dependency file changed (+0.15)")

    by_mod = stats.get("by_module", {})
    for m in modules:
        if m in by_mod:
            prob = max(prob, by_mod[m])
            drivers.append(f"[TRANSFER] module={m} historical P(prod_fail|dev_pass)={by_mod[m]:.2f}")

    by_sig = stats.get("by_signal", {})
    for s in signals:
        if s in by_sig:
            prob = max(prob, by_sig[s])
            drivers.append(f"[TRANSFER] signal={s} rate={by_sig[s]:.2f}")

    similar = []
    for p in pairs:
        if p.dev_status not in config.FINISHED_STATUSES:
            continue
        sim = _jaccard(modules, p.dev_modules) * 0.5 + _jaccard(signals, p.dev_log_signals) * 0.5
        if sim >= 0.3:
            similar.append((sim, p))

    similar.sort(key=lambda x: -x[0])
    top = similar[:6]
    if top:
        fails = sum(1 for _, p in top if p.prod_failed_after_dev_pass)
        if len(top) >= config.MIN_PAIR_SAMPLES:
            pair_rate = fails / len(top)
            prob = max(prob, pair_rate)
            conf = "medium" if len(top) >= 5 else "low"
            drivers.append(
                f"[PAIRS] {fails}/{len(top)} similar dev_pass cases failed prod"
            )
            for _, p in top[:3]:
                drivers.append(f"  → {p.dev_execution_id}→{p.prod_execution_id} ({p.label})")
        else:
            conf = "low"
            drivers.append(f"[PAIRS] only {len(top)} similar pairs (need {config.MIN_PAIR_SAMPLES})")
    else:
        conf = "low"
        drivers.append("[PAIRS] no similar historical pairs")

    prob = min(max(prob, 0.05), 0.95)
    risk = "High" if prob >= 0.6 else "Medium" if prob >= 0.35 else "Low"
    if not stats:
        conf = "low"
        drivers.insert(0, "[WARN] Run pipeline-risk index --rebuild first")

    return TrackScore(
        prob=round(prob, 4),
        risk=risk,
        confidence=conf if top else "low",
        drivers=drivers,
        n_samples=len(top),
    )
