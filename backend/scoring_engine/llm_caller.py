"""
Shared LLM calling utility for the scoring engine.

Uses centralized llm.get_provider(). Supports OpenAI, Gemini, OpenRouter.
Temperature=0, strict JSON, consistent error handling. Catches ProviderError and returns None
to preserve existing pipeline behavior.
"""
import re
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("btc_macro.llm_caller")


def call_llm_json(
    prompt: str,
    system_message: str = "You are a macro-economic analyst. Output only valid JSON.",
    model: str = "gpt-4o",
    temperature: float = 0,
    max_tokens: int = 256,
) -> Optional[Dict[str, Any]]:
    """Call LLM and return parsed JSON, or None on failure.

    Uses LLM_PROVIDER / OPENAI_API_KEY / GEMINI_API_KEY. Raises are caught and
    converted to None so callers keep existing fallback behavior.
    """
    try:
        from llm import get_provider, ProviderError
    except ImportError:
        from llm.provider_factory import get_provider
        from llm.provider_interface import ProviderError

    try:
        provider = get_provider()
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]
        raw = provider.chat(
            messages,
            model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ProviderError as e:
        logger.warning("LLM call failed: %s", e)
        return None
    except ValueError as e:
        logger.warning("LLM provider not configured: %s", e)
        return None

    return _parse_json(raw)


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM JSON: %s", raw[:200])
    return None
