"""
Headline classification using LLM.

LLM is used ONLY here — for classifying macro headlines.
- temperature = 0 (deterministic)
- Strict JSON output
- Schema validation
- No narrative generation
- Keyword-based rule fallback when LLM fails (prevents neutral default-spam)
"""
import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

# ── Keyword-based deterministic fallback ──────────────────────────────────────
# Applied when LLM fails to return valid JSON. Prevents cascading neutral defaults.
_HAWKISH_WORDS = [
    "rate hike", "hawkish", "higher for longer", "inflation sticky",
    "tighten", "premature easing", "labor market strong", "upside risk",
    "overheat", "aggressive", "restrictive policy",
]
_DOVISH_WORDS = [
    "rate cut", "dovish", "pivot", "disinflation", "policy is restrictive",
    "easing", "balanced risks", "financial conditions tightening",
    "slowdown", "recession fears", "soft landing",
]
_RISK_OFF_WORDS = [
    "drops", "falls", "crash", "warning", "selloff", "bear",
    "war", "tension", "sanctions", "tariff", "bank failure", "crisis",
    "head-and-shoulders", "breakdown", "risk-off", "flight to safety",
]
_RISK_ON_WORDS = [
    "rally", "surge", "bull", "breakout", "risk-on", "growth beats",
    "strong jobs", "optimism", "record high",
]


def _keyword_classify(title: str, description: str) -> Dict[str, Any]:
    """Deterministic keyword-based fallback classifier."""
    text = (title + " " + (description or "")).lower()

    hawkish_hits = sum(1 for w in _HAWKISH_WORDS if w in text)
    dovish_hits = sum(1 for w in _DOVISH_WORDS if w in text)
    risk_off_hits = sum(1 for w in _RISK_OFF_WORDS if w in text)
    risk_on_hits = sum(1 for w in _RISK_ON_WORDS if w in text)

    if hawkish_hits > dovish_hits:
        bias = "hawkish"
    elif dovish_hits > hawkish_hits:
        bias = "dovish"
    else:
        bias = "neutral"

    if risk_off_hits > risk_on_hits:
        impact = "risk_off"
    elif risk_on_hits > risk_off_hits:
        impact = "risk_on"
    else:
        impact = "neutral"

    conf = min(0.7, 0.3 + 0.1 * max(hawkish_hits, dovish_hits, risk_off_hits, risk_on_hits))

    return {
        "event_bias": bias,
        "risk_impact": impact,
        "confidence": round(conf, 2),
        "reason": f"Keyword fallback: hawkish={hawkish_hits} dovish={dovish_hits} risk_off={risk_off_hits} risk_on={risk_on_hits}",
        "_keyword_fallback": True,
    }

load_dotenv()

logger = logging.getLogger("btc_macro.headline_engine")


def _load_llm_config() -> Dict:
    config_path = Path(__file__).parent.parent / "config" / "llm_config.json"
    with open(config_path, "r") as f:
        return json.load(f)


LLM_CONFIG = _load_llm_config()

# Expected output schema for validation
EXPECTED_KEYS = {"event_bias", "risk_impact", "confidence", "reason"}
VALID_BIASES = {"hawkish", "dovish", "neutral"}
VALID_IMPACTS = {"risk_on", "risk_off", "neutral"}


class HeadlineClassifier:
    """Classifies macro headlines using LLM with deterministic settings."""
    
    def __init__(self):
        self.config = LLM_CONFIG["headline_classification"]
        self.prompt_template = LLM_CONFIG["headline_prompt_template"]
        self.prompt_version = self.config["prompt_version"]
        self.model = self.config["model"]
        try:
            from llm import get_provider
            self._provider = get_provider()
        except ImportError:
            from llm.provider_factory import get_provider
            self._provider = get_provider()
    
    def classify_headlines(self, headlines: List[Dict]) -> List[Dict[str, Any]]:
        """
        Classify a batch of headlines.
        
        Args:
            headlines: List of dicts with 'title' and 'description'
        
        Returns:
            List of classification dicts, each with:
                event_bias, risk_impact, confidence, reason, _headline_title, _raw_response
        """
        results = []
        for h in headlines:
            try:
                classification = self.classify_single(
                    h.get("title", ""),
                    h.get("description", "")
                )
                classification["_headline_title"] = h.get("title", "")
                results.append(classification)
            except Exception as e:
                logger.warning(f"Failed to classify headline: {h.get('title', '')[:60]}... Error: {e}")
                # Apply keyword-based rule fallback before defaulting to neutral
                kw = _keyword_classify(h.get("title", ""), h.get("description", ""))
                kw["_headline_title"] = h.get("title", "")
                kw["_error"] = str(e)
                kw["reason"] = f"Keyword fallback (LLM failed): {kw['reason']}"
                results.append(kw)
        
        return results
    
    def classify_single(self, headline: str, description: str) -> Dict[str, Any]:
        """
        Classify a single headline.
        
        Returns validated dict with: event_bias, risk_impact, confidence, reason
        """
        prompt = self.prompt_template.format(
            headline=headline.replace('"', "'"),
            description=(description or "").replace('"', "'")[:300],
        )
        
        try:
            from llm.provider_interface import ProviderError
        except ImportError:
            ProviderError = Exception
        try:
            messages = [
                {"role": "system", "content": "You are a macro-economic event classifier. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ]
            raw = self._provider.chat(
                messages,
                self.model,
                temperature=0,
                max_tokens=self.config["max_tokens"],
            )
        except (ProviderError, ValueError) as e:
            logger.warning("LLM classify failed: %s", e)
            raise
        
        # Parse and validate JSON. If parsing fails, apply deterministic keyword fallback
        try:
            parsed = self._parse_json_response(raw)
            validated = self._validate_output(parsed)
            validated["_raw_response"] = raw
            validated["_model"] = self.model
            validated["_prompt_version"] = self.prompt_version
            return validated
        except ValueError as e:
            logger.warning("LLM returned invalid JSON for headline (%s): %s -- using keyword fallback", headline[:80], str(e))
            kw = _keyword_classify(headline, description)
            kw["_raw_response"] = raw
            kw["_model"] = "keyword_fallback"
            kw["_prompt_version"] = self.prompt_version
            return kw
    
    def _parse_json_response(self, raw: str) -> Dict:
        """Parse JSON from LLM response, handling markdown fences and truncation."""
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object via regex (handles trailing garbage)
        match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Try to repair truncated JSON by closing open string + object
        repaired = text.rstrip()
        if not repaired.endswith('}'):
            # Close any open string then close the object
            if repaired.count('"') % 2 == 1:
                repaired += '"'
            repaired += '}'
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

        raise ValueError(f"LLM returned invalid JSON: {raw[:200]}")
    
    def _validate_output(self, parsed: Dict) -> Dict:
        """Validate parsed output against expected schema."""
        # Check required keys
        missing = EXPECTED_KEYS - set(parsed.keys())
        if missing:
            raise ValueError(f"Missing keys in LLM output: {missing}")
        
        # Validate enum values
        if parsed["event_bias"] not in VALID_BIASES:
            parsed["event_bias"] = "neutral"
            logger.warning(f"Invalid event_bias, defaulted to neutral")
        
        if parsed["risk_impact"] not in VALID_IMPACTS:
            parsed["risk_impact"] = "neutral"
            logger.warning(f"Invalid risk_impact, defaulted to neutral")
        
        # Validate confidence range
        conf = parsed.get("confidence", 0)
        if not isinstance(conf, (int, float)):
            conf = 0.0
        parsed["confidence"] = max(0.0, min(1.0, float(conf)))
        
        # Validate reason is string
        if not isinstance(parsed.get("reason"), str):
            parsed["reason"] = str(parsed.get("reason", ""))
        
        return parsed
