"""
Shared LLM calling utility for the scoring engine.

Uses centralized llm.get_provider() (OpenAI only).
Temperature=0, strict JSON, consistent error handling. Catches ProviderError and returns None
to preserve existing pipeline behavior.
"""
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("btc_macro.llm_caller")


def call_llm_json(
    prompt: str,
    system_message: str = "You are a macro-economic analyst. Output only valid JSON.",
    model: str = "gpt-4o",
    temperature: float = 0,
    max_tokens: int = 256,
    required_keys: Optional[List[str]] = None,
    strict_json: bool = True,
) -> Optional[Dict[str, Any]]:
    """Call LLM and return parsed JSON, or None on failure.

    Uses OPENAI_API_KEY. Raises are caught and converted to None so callers
    keep existing fallback behavior.
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
            response_format={"type": "json_object"} if strict_json else None,
        )
    except ProviderError as e:
        logger.warning("LLM call failed: %s", e)
        return None
    except ValueError as e:
        logger.warning("LLM provider not configured: %s", e)
        return None

    parsed = _parse_json(raw, strict_json=strict_json)
    if parsed is None:
        return None

    if required_keys and not _has_required_keys(parsed, required_keys):
        logger.warning(
            "LLM JSON contract failed. Missing keys=%s, payload=%s",
            [k for k in required_keys if k not in parsed],
            str(parsed)[:200],
        )
        return None
    return parsed


def _parse_json(raw: str, strict_json: bool = True) -> Optional[Dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        # In strict mode, reject malformed or mixed-content payloads.
        if strict_json:
            logger.warning("Strict JSON parse failed: %s", raw[:200])
            return None

    extracted = _extract_first_json_object(text)
    if extracted:
        try:
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM JSON: %s", raw[:200])
    return None


def _extract_first_json_object(text: str) -> Optional[str]:
    """Extract first top-level JSON object from mixed text payload."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _has_required_keys(payload: Dict[str, Any], required_keys: List[str]) -> bool:
    return all(key in payload for key in required_keys)
