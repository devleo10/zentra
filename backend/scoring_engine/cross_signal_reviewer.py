"""
LLM-powered cross-signal anomaly detector.

After the 5 deterministic section scores are computed, this module sends
them (plus key raw data) to an LLM to detect contradictions that the
independent scoring cannot see.

The LLM output is a bounded adjustment (-5 to +5) hard-capped in code.
On any failure the adjustment is 0 (no change).
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple

logger = logging.getLogger("btc_macro.cross_signal")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_config.json"

_HARD_CAP = 5


def review_cross_signals(
    section_scores: Dict[str, int],
    section_reasoning: Dict[str, str],
    raw_data: Dict[str, Any],
) -> Tuple[int, str, list]:
    """
    Ask LLM to review all section scores for contradictions.

    Returns:
        (adjustment, reasoning, signals_to_watch)
        adjustment: integer in [-5, +5]
        reasoning: string explanation (empty on fallback)
        signals_to_watch: list of signal names to monitor
    """
    try:
        from scoring_engine.llm_caller import call_llm_json

        with open(_CONFIG_PATH) as f:
            cfg = json.load(f).get("cross_signal_review", {})

        vix = raw_data.get("vix", {}).get("current_value")
        dxy = raw_data.get("dxy", {}).get("current_price")
        gold_change = raw_data.get("gold", {}).get("change")
        sp500_change = raw_data.get("sp500", {}).get("change")
        btc_price = raw_data.get("btc", {}).get("price_usd")
        fed_rate = raw_data.get("fed_rate", {}).get("current_rate")

        prompt = (
            "You are a cross-signal macro analyst reviewing 5 independently-scored macro sections "
            "for contradictions or anomalies the deterministic engine may have missed.\n\n"
            "SECTION SCORES (each 0-100, higher = more bullish for BTC):\n"
        )
        for name, score in section_scores.items():
            reason = section_reasoning.get(name, "")
            prompt += f"  {name}: {score}/100 — {reason}\n"

        prompt += (
            f"\nKEY RAW DATA:\n"
            f"  VIX: {vix}\n"
            f"  DXY: {dxy}\n"
            f"  Gold change: {gold_change}%\n"
            f"  S&P 500 change: {sp500_change}%\n"
            f"  BTC price: ${btc_price}\n"
            f"  Fed Funds Rate: {fed_rate}%\n"
            "\nOutput ONLY valid JSON:\n"
            "{\n"
            '  "contradictions_found": true | false,\n'
            '  "adjustment": <integer -5 to +5>,\n'
            '  "reasoning": "<one paragraph explaining what the deterministic engine missed>",\n'
            '  "signals_to_watch": ["signal 1", "signal 2"]\n'
            "}\n\n"
            "Rules:\n"
            "- adjustment MUST be between -5 and +5 inclusive\n"
            "- Positive = the overall picture is more bullish than the weighted score implies\n"
            "- Negative = the overall picture is more bearish than the weighted score implies\n"
            "- 0 = the scores look internally consistent\n"
            "- Look for contradictions like low VIX + surging gold (conflicting risk signals), "
            "or strong inflation + dovish policy (incoherent), etc.\n"
        )

        result = call_llm_json(
            prompt=prompt,
            system_message="You are a cross-signal macro analyst. Output only valid JSON.",
            model=cfg.get("model", "gpt-4o"),
            temperature=cfg.get("temperature", 0),
            max_tokens=cfg.get("max_tokens", 300),
        )

        if result is None:
            raise ValueError("LLM returned None")

        adj = int(result.get("adjustment", 0))
        adj = max(-_HARD_CAP, min(_HARD_CAP, adj))

        reasoning = str(result.get("reasoning", ""))
        signals = result.get("signals_to_watch", [])
        if not isinstance(signals, list):
            signals = []

        logger.info(
            "Cross-signal review: adjustment=%+d, contradictions=%s",
            adj, result.get("contradictions_found", False),
        )
        return adj, reasoning, signals

    except Exception as e:
        logger.warning("Cross-signal review failed (%s), defaulting to 0 adjustment", e)
        return 0, "", []
