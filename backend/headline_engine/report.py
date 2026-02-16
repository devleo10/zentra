"""
Market report generator for classified headlines.

Produces a concise human-readable report summarizing explicit decisions,
aggregate tone, top headlines, and a preview adjustment using the existing
headline_adjuster logic.
"""
from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger("btc_macro.headline_engine.report")

from ..scoring_engine.headline_adjuster import compute_headline_adjustment


def generate_market_report(classified_headlines: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Generate a text report and metadata from classified headlines.

    Returns (text_report, metadata_dict)
    """
    meta = {
        "total_headlines": len(classified_headlines),
        "explicit_decisions": [],
        "by_bias": {},
        "by_impact": {},
        "avg_confidence": 0.0,
    }

    if not classified_headlines:
        return ("No headlines available.", meta)

    # Collect stats
    total_conf = 0.0
    for h in classified_headlines:
        bias = h.get("event_bias", "neutral")
        impact = h.get("risk_impact", "neutral")
        meta["by_bias"][bias] = meta["by_bias"].get(bias, 0) + 1
        meta["by_impact"][impact] = meta["by_impact"].get(impact, 0) + 1
        conf = float(h.get("confidence", 0) or 0)
        total_conf += conf
        if h.get("_explicit_decision"):
            meta["explicit_decisions"].append({
                "title": h.get("_headline_title", h.get("title", ""))[:200],
                "decision_type": h.get("_decision_type"),
                "source": h.get("source"),
                "confidence": conf,
            })

    meta["avg_confidence"] = total_conf / len(classified_headlines) if classified_headlines else 0.0

    # Suggested adjustment preview (uses existing deterministic logic)
    suggested_adj, reasoning = compute_headline_adjustment(classified_headlines)
    meta["suggested_adjustment"] = suggested_adj
    meta["adjustment_reasoning"] = reasoning

    # Top headlines by confidence and authority (simple sort)
    sorted_headlines = sorted(
        classified_headlines,
        key=lambda x: (x.get("_authority_score", 0), x.get("confidence", 0)),
        reverse=True,
    )

    top = []
    for h in sorted_headlines[:5]:
        top.append({
            "title": h.get("_headline_title", h.get("title", ""))[:200],
            "bias": h.get("event_bias"),
            "impact": h.get("risk_impact"),
            "confidence": h.get("confidence", 0),
            "explicit_decision": h.get("_explicit_decision", False),
            "decision_type": h.get("_decision_type"),
            "source": h.get("source"),
        })

    meta["top_headlines"] = top

    # Build plain-text report
    lines = []
    lines.append("MARKET NEWS REPORT")
    lines.append("------------------")
    lines.append(f"Headlines analyzed: {meta['total_headlines']}")
    lines.append(f"Average classification confidence: {meta['avg_confidence']:.2f}")
    lines.append("")
    if meta["explicit_decisions"]:
        lines.append("Explicit decisions detected:")
        for d in meta["explicit_decisions"]:
            lines.append(f" - [{d['decision_type']}] {d['title']} (src={d.get('source')}, conf={d['confidence']:.2f})")
        lines.append("")

    lines.append("Aggregate tone:")
    for b, cnt in meta["by_bias"].items():
        lines.append(f" - {b}: {cnt}")
    for i, cnt in meta["by_impact"].items():
        lines.append(f" - impact {i}: {cnt}")
    lines.append("")
    lines.append(f"Suggested headline adjustment (preview): {suggested_adj:+d}")
    lines.append(f"Adjustment reasoning: {reasoning}")
    lines.append("")
    lines.append("Top headlines:")
    for t in top:
        lines.append(f" - {t['title']} [{t['bias']}/{t['impact']} conf={t['confidence']:.2f}] (explicit={t['explicit_decision']})")

    text_report = "\n".join(lines)
    logger.info("Generated market report; suggested_adj=%s avg_conf=%.2f", suggested_adj, meta["avg_confidence"])

    return text_report, meta
