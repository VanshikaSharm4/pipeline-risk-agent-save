"""Combine Track A + Track B for enterprise gate (weights from config)."""

from __future__ import annotations

import os
from typing import Optional, Tuple

from models.schemas import TrackScore

TRACK_A_WEIGHT = float(os.getenv("TRACK_A_WEIGHT", "0.6"))
TRACK_B_WEIGHT = float(os.getenv("TRACK_B_WEIGHT", "0.4"))


def combine_tracks(
    structured: TrackScore,
    vector: Optional[TrackScore],
) -> Tuple[TrackScore, str]:
    """
    Returns (combined TrackScore, agreement_note).
    If vector has no samples, combined = structured only.
    """
    if vector is None or vector.n_samples == 0:
        return structured, "Track B unavailable — using Track A only"

    w_a, w_b = TRACK_A_WEIGHT, TRACK_B_WEIGHT
    prob = min(max(w_a * structured.prob + w_b * vector.prob, 0.05), 0.95)
    risk = "High" if prob >= 0.6 else "Medium" if prob >= 0.35 else "Low"

    agree = structured.risk == vector.risk
    if agree:
        note = f"Tracks agree ({structured.risk}) — combined confidence higher"
        conf = "high" if structured.confidence == "high" or vector.confidence == "medium" else "medium"
    else:
        note = f"Tracks disagree: A={structured.risk} ({structured.prob:.0%}) vs B={vector.risk} ({vector.prob:.0%}) — review both"
        conf = "medium"

    drivers = [
        f"[COMBINED] {w_a:.0%}×TrackA + {w_b:.0%}×TrackB = {prob:.0%}",
        *structured.drivers[:3],
        *vector.drivers[:3],
    ]

    combined = TrackScore(
        prob=round(prob, 4),
        risk=risk,
        confidence=conf,
        drivers=drivers,
        n_samples=structured.n_samples + vector.n_samples,
        extra={"track_a_weight": w_a, "track_b_weight": w_b, "agreement": agree},
    )
    return combined, note
