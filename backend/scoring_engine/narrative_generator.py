"""
LLM-powered narrative generator for the final verdict.

Produces a 2-3 sentence actionable market commentary, the single biggest
risk, and the next catalyst to watch.

Falls back to the existing template reasoning string on any failure.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("btc_macro.narrative")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_config.json"


def generate_narrative(
    final_score: int,
    bias: str,
    action: str,
    section_scores: Dict[str, int],
    section_reasoning: Dict[str, str],
    headline_adjustment: int,
    cross_signal_adjustment: int,
    cross_signal_reasoning: str,
    raw_data: Dict[str, Any],
    classified_headlines: Optional[List[Dict[str, Any]]] = None,
    freshness_info: Optional[Dict[str, Any]] = None,
    template_reasoning: str = "",
) -> Dict[str, str]:
    """
    Generate a rich narrative explanation of the verdict.

    Returns:
        {
            "narrative": "2-3 sentence commentary",
            "key_risk": "single biggest risk",
            "catalyst_to_watch": "next data point that could change things"
        }
    On failure, returns template fallback values.
    """
    fallback = {
        "narrative": _build_data_cited_fallback(
            final_score=final_score,
            bias=bias,
            action=action,
            raw_data=raw_data,
            classified_headlines=classified_headlines or [],
            freshness_info=freshness_info or {},
            template_reasoning=template_reasoning,
        ),
        "key_risk": "",
        "catalyst_to_watch": "",
    }

    try:
        from scoring_engine.llm_caller import call_llm_json

        with open(_CONFIG_PATH) as f:
            cfg = json.load(f).get("narrative_generation", {})

        vix = raw_data.get("vix", {}).get("current_value")
        btc_price = raw_data.get("btc", {}).get("price_usd")
        fed_rate = raw_data.get("fed_rate", {}).get("current_rate")
        cpi_yoy = raw_data.get("cpi", {}).get("yoy_rate")
        cpi_core = raw_data.get("cpi", {}).get("core_yoy_rate")
        dxy = raw_data.get("dxy", {}).get("current_price")
        ten_y = raw_data.get("yields", {}).get("yield_10y", {}).get("value")
        wti = raw_data.get("oil", {}).get("current_price")

        headline_context = ""
        if classified_headlines:
            top = classified_headlines[:3]
            lines = []
            for h in top:
                title = h.get("_headline_title", "")[:120]
                event_bias = h.get("event_bias", "neutral")
                risk_impact = h.get("risk_impact", "neutral")
                conf = h.get("confidence", 0)
                lines.append(f"- {title} [bias={event_bias}, impact={risk_impact}, conf={conf}]")
            headline_context = "\nRecent Headlines Context:\n" + "\n".join(lines)

        freshness_context = ""
        if freshness_info:
            checks = freshness_info.get("checks", [])
            if checks:
                fresh = sum(1 for c in checks if str(c.get("status", "")).upper() == "FRESH")
                total = len(checks)
                freshness_context = f"\nData Freshness: {fresh}/{total} checks fresh."

        prompt = (
            "You are a senior crypto macro strategist writing a concise market brief.\n\n"
            f"VERDICT: Score {final_score}/100, Bias: {bias}, Action: {action}\n\n"
            "SECTION SCORES:\n"
        )
        for name, score in section_scores.items():
            reason = section_reasoning.get(name, "")
            prompt += f"  {name}: {score}/100 — {reason}\n"

        prompt += f"\nHeadline adjustment: {headline_adjustment:+d}\n"
        if cross_signal_adjustment:
            prompt += f"Cross-signal adjustment: {cross_signal_adjustment:+d} — {cross_signal_reasoning}\n"

        prompt += (
            f"\nKEY DATA: CPI YoY={cpi_yoy}%, Core CPI={cpi_core}%, Fed Rate={fed_rate}%, "
            f"10Y={ten_y}%, DXY={dxy}, VIX={vix}, WTI=${wti}, BTC=${btc_price}"
            f"{freshness_context}"
            f"{headline_context}\n\n"
            "Hard requirement: cite at least 3 numeric metrics from KEY DATA directly in the narrative.\n"
            "If headline context includes geopolitical events (war/sanctions/tariffs/press conference), mention their "
            "market impact explicitly.\n\n"
            "Write a JSON response with exactly this format:\n"
            "{\n"
            '  "narrative": "<2-3 sentences explaining the market picture and what it means for BTC. '
            'Write like a Bloomberg macro note — concise, data-driven, actionable.>",\n'
            '  "key_risk": "<the single biggest risk to this thesis, in one sentence>",\n'
            '  "catalyst_to_watch": "<the next upcoming data point or event that could shift the picture>"\n'
            "}\n"
        )

        result = call_llm_json(
            prompt=prompt,
            system_message="You are a senior crypto macro strategist. Output only valid JSON.",
            model=cfg.get("model", "gpt-4o"),
            temperature=cfg.get("temperature", 0.2),
            max_tokens=cfg.get("max_tokens", 350),
            required_keys=["narrative", "key_risk", "catalyst_to_watch"],
            strict_json=True,
        )

        if result is None:
            raise ValueError("LLM returned None")

        narrative = str(result.get("narrative", "")).strip()
        key_risk = str(result.get("key_risk", "")).strip()
        catalyst = str(result.get("catalyst_to_watch", "")).strip()

        if not narrative:
            raise ValueError("Empty narrative from LLM")
        if not _is_data_cited_narrative(narrative):
            logger.warning("Narrative too generic, switching to deterministic data-cited fallback")
            return fallback

        narrative = _augment_with_event_context(narrative, classified_headlines or [])

        if not _narrative_matches_bias(narrative, bias, final_score):
            logger.warning("Narrative tone inconsistent with verdict; using data-cited fallback text")
            narrative = fallback["narrative"]

        logger.info("Narrative generated: %s...", narrative[:120])

        return {
            "narrative": narrative,
            "key_risk": key_risk,
            "catalyst_to_watch": catalyst,
        }

    except Exception as e:
        logger.warning("Narrative generation failed (%s), using template fallback", e)
        return fallback


def _is_data_cited_narrative(text: str) -> bool:
    """
    Heuristic: ensure narrative includes several numeric citations.
    """
    import re
    numeric_hits = re.findall(r"\d+(?:\.\d+)?%|\$\d+(?:,\d{3})*(?:\.\d+)?|\b\d{2,3}\b", text)
    return len(numeric_hits) >= 3


def _build_data_cited_fallback(
    final_score: int,
    bias: str,
    action: str,
    raw_data: Dict[str, Any],
    classified_headlines: List[Dict[str, Any]],
    freshness_info: Dict[str, Any],
    template_reasoning: str,
) -> str:
    """
    Deterministic narrative fallback with hard metric citations.
    """
    cpi = raw_data.get("cpi", {})
    dxy = raw_data.get("dxy", {})
    vix = raw_data.get("vix", {})
    oil = raw_data.get("oil", {})
    yields = raw_data.get("yields", {})
    btc = raw_data.get("btc", {})
    fed = raw_data.get("fed_rate", {})

    metric_line = (
        f"CPI {cpi.get('yoy_rate', 'N/A')}% (core {cpi.get('core_yoy_rate', 'N/A')}%), "
        f"Fed funds {fed.get('current_rate', 'N/A')}%, 10Y {yields.get('yield_10y', {}).get('value', 'N/A')}%, "
        f"DXY {dxy.get('current_price', 'N/A')}, VIX {vix.get('current_value', 'N/A')}, "
        f"WTI ${oil.get('current_price', 'N/A')}, BTC ${btc.get('price_usd', 'N/A')}."
    )

    geopolit_line = ""
    if classified_headlines:
        joined = " ".join((h.get("_headline_title", "") or "").lower() for h in classified_headlines[:5])
        if any(k in joined for k in ["war", "iran", "israel", "ukraine", "russia", "tariff", "sanction", "trump", "press conference"]):
            geopolit_line = " Recent headlines indicate active geopolitical/policy event risk, which can amplify oil and volatility shocks."

    freshness_line = ""
    checks = freshness_info.get("checks", [])
    if checks:
        fresh = sum(1 for c in checks if str(c.get("status", "")).upper() == "FRESH")
        freshness_line = f" Data freshness checks are {fresh}/{len(checks)} fresh."

    base = f"Macro score is {final_score}/100 ({bias}) with action: {action}. {metric_line}{geopolit_line}{freshness_line}"
    if template_reasoning and template_reasoning.startswith("Numeric:"):
        return base
    return base


def _narrative_matches_bias(narrative: str, _bias: str, final_score: int) -> bool:
    """Lightweight keyword check: narrative should not contradict the score in obvious ways."""
    import re

    t = narrative.lower()
    has_bear = bool(re.search(r"\bbearish\b", t))
    has_bull = bool(re.search(r"\bbullish\b", t))
    if final_score >= 68 and has_bear and not has_bull:
        return False
    if final_score <= 32 and has_bull and not has_bear:
        return False
    return True


def _augment_with_event_context(narrative: str, classified_headlines: List[Dict[str, Any]]) -> str:
    """
    Ensure narrative references concrete ongoing policy/geopolitical events when present.
    Only appends risk-off language if at least one top headline is classified risk_off.
    """
    if not classified_headlines:
        return narrative

    titles = [str(h.get("_headline_title", "") or "") for h in classified_headlines[:8]]
    text = " ".join(titles).lower()
    top = classified_headlines[:8]
    any_risk_off = any(h.get("risk_impact") == "risk_off" for h in top)

    event_fragments = []
    if any(k in text for k in ["fomc", "federal reserve", "powell", "fed"]):
        event_fragments.append("recent Fed releases")
    if any(k in text for k in ["trump", "white house", "press conference", "executive order"]):
        event_fragments.append("US policy headlines including Trump/White House updates")
    if any(k in text for k in ["war", "iran", "israel", "ukraine", "russia", "middle east", "sanction", "tariff"]):
        event_fragments.append("ongoing war/geopolitical headlines")

    if not event_fragments:
        return narrative

    existing = narrative.lower()
    if any(fragment.split()[0] in existing for fragment in event_fragments):
        return narrative

    if any_risk_off:
        suffix = " are contributing to risk-off volatility."
    else:
        suffix = " are adding headline-driven uncertainty; monitor cross-asset moves."

    extra = " Event context: " + ", ".join(event_fragments) + suffix
    return (narrative + extra).strip()
