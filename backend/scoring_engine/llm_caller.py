"""
Shared LLM calling utility for the scoring engine.

Provides a single function to call OpenAI or Gemini with temperature=0,
strict JSON output, and consistent error handling.
"""
import os
import re
import json
import time
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("btc_macro.llm_caller")


def call_llm_json(
    prompt: str,
    system_message: str = "You are a macro-economic analyst. Output only valid JSON.",
    model: str = "gpt-4o",
    temperature: float = 0,
    max_tokens: int = 256,
) -> Optional[Dict[str, Any]]:
    """Call LLM and return parsed JSON, or None on failure.

    Tries OpenAI first, then Gemini, then returns None.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    raw = None
    if openai_key:
        raw = _call_openai(prompt, system_message, model, temperature, max_tokens, openai_key)
    elif gemini_key:
        raw = _call_gemini(prompt, system_message, temperature, max_tokens, gemini_key)

    if raw is None:
        return None

    return _parse_json(raw)


def _call_openai(
    prompt: str, system_msg: str, model: str, temperature: float, max_tokens: int, api_key: str
) -> Optional[str]:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("OpenAI call failed: %s", e)
        return None


def _call_gemini(
    prompt: str, system_msg: str, temperature: float, max_tokens: int, api_key: str
) -> Optional[str]:
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    try:
        from google import genai as genai_new
        from google.genai import types as genai_types
        client = genai_new.Client(api_key=api_key)
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=gemini_model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        system_instruction=system_msg,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    wait = 15 * (attempt + 1)
                    logger.warning("Gemini rate-limited (attempt %d/3), waiting %ds", attempt + 1, wait)
                    time.sleep(wait)
                    continue
                raise
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Gemini call failed: %s", e)
    return None


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
