"""
LLM-powered narrative generator for the final verdict.

Produces a 2-3 sentence actionable market commentary, the single biggest
risk, and the next catalyst to watch.

Falls back to the existing template reasoning string on any failure.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

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
        "narrative": template_reasoning or f"Score {final_score}/100. Bias: {bias}. Action: {action}.",
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
        dxy = raw_data.get("dxy", {}).get("current_price")

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
            f"\nKEY DATA: VIX={vix}, DXY={dxy}, BTC=${btc_price}, "
            f"Fed Rate={fed_rate}%, CPI YoY={cpi_yoy}%\n\n"
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
        )

        if result is None:
            raise ValueError("LLM returned None")

        narrative = str(result.get("narrative", "")).strip()
        key_risk = str(result.get("key_risk", "")).strip()
        catalyst = str(result.get("catalyst_to_watch", "")).strip()

        if not narrative:
            raise ValueError("Empty narrative from LLM")

        logger.info("Narrative generated: %s...", narrative[:120])

        return {
            "narrative": narrative,
            "key_risk": key_risk,
            "catalyst_to_watch": catalyst,
        }

    except Exception as e:
        logger.warning("Narrative generation failed (%s), using template fallback", e)
        return fallback
