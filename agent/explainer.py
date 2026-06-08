"""Template-based dual-track report."""

from __future__ import annotations

from models.schemas import ProdRiskReport, TrackScore


def render_report(
    dev_execution_id: str,
    commit_sha: str | None,
    structured: TrackScore,
    vector: TrackScore | None,
    combined: TrackScore | None = None,
    combination_note: str = "",
) -> str:
    lines = [
        f"# Prod risk report — dev execution {dev_execution_id}",
        "",
    ]
    if commit_sha:
        lines.append(f"**Commit:** `{commit_sha}`")
        lines.append("")

    lines.extend([
        "## Track A (structured)",
        f"- **Risk:** {structured.risk}",
        f"- **Probability:** {structured.prob:.0%}",
        f"- **Confidence:** {structured.confidence} (n={structured.n_samples})",
        "",
        "**Drivers:**",
    ])
    for d in structured.drivers:
        lines.append(f"- {d}")

    if vector:
        lines.extend([
            "",
            "## Track B (vector)",
            f"- **Risk:** {vector.risk}",
            f"- **Probability:** {vector.prob:.0%}",
            f"- **Confidence:** {vector.confidence} (n={vector.n_samples})",
            "",
            "**Drivers:**",
        ])
        for d in vector.drivers:
            lines.append(f"- {d}")

        agree = structured.risk == vector.risk
        lines.extend([
            "",
            f"**Agreement:** {'YES' if agree else 'NO'}",
        ])

    if combined:
        lines.extend([
            "",
            "## Combined (enterprise gate)",
            f"- **Risk:** {combined.risk}",
            f"- **Probability:** {combined.prob:.0%}",
            f"- **Confidence:** {combined.confidence}",
            f"- {combination_note}",
            "",
            "**Combined drivers:**",
        ])
        for d in combined.drivers[:6]:
            lines.append(f"- {d}")

    rec = _recommendation(combined or structured, vector)
    lines.extend(["", f"**Recommendation:** {rec}"])
    return "\n".join(lines)


def _recommendation(structured: TrackScore, vector: TrackScore | None) -> str:
    high = structured.risk == "High" or (vector and vector.risk == "High")
    med = structured.risk == "Medium" or (vector and vector.risk == "Medium")
    if high:
        return "DO_NOT_PROMOTE"
    if med:
        return "PROMOTE_WITH_CAUTION"
    return "OK_TO_PROMOTE"
