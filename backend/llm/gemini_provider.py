"""
Gemini provider using google.genai SDK with 429 retry.
"""
import os
import time
import logging
from typing import List, Dict, Any

from llm.provider_interface import LLMProvider, ProviderError

logger = logging.getLogger("btc_macro.llm.gemini")

DEFAULT_MODEL = "gemini-2.0-flash"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 15


def _is_retryable(e: Exception) -> bool:
    err = str(e).lower()
    return "429" in str(e) or "quota" in err


class GeminiProvider(LLMProvider):
    """Gemini via google.genai. No base_url; uses GEMINI_MODEL env."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None
        self._model_default = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    def _get_client(self):
        if self._client is None:
            from google import genai as genai_new
            self._client = genai_new.Client(api_key=self._api_key)
        return self._client

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        temperature: float = 0,
        max_tokens: int = 256,
    ) -> str:
        from google.genai import types as genai_types
        client = self._get_client()
        use_model = model if (model and "gemini" in model.lower()) else self._model_default
        system_msg = ""
        chat_messages = []
        for m in messages:
            role = (m.get("role") or "user").lower()
            content = (m.get("content") or "").strip()
            if role == "system":
                system_msg = content
            else:
                chat_messages.append({"role": role, "content": content})
        if not chat_messages:
            raise ProviderError("No user or assistant messages", provider="gemini")
        # Build single prompt with system if needed; Gemini accepts system_instruction
        prompt = chat_messages[-1]["content"] if chat_messages else ""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=use_model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        system_instruction=system_msg or None,
                    ),
                )
                return (response.text or "").strip()
            except Exception as e:
                last_error = e
                if _is_retryable(e) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE * (attempt + 1)
                    logger.warning(
                        "Gemini rate-limited (attempt %d/%d), waiting %ds",
                        attempt + 1, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                raise ProviderError(
                    f"Gemini chat failed: {e}",
                    provider="gemini",
                    cause=e,
                )
        raise ProviderError(
            f"Gemini chat failed after {MAX_RETRIES} attempts: {last_error}",
            provider="gemini",
            cause=last_error,
        )

    def embed(self, texts: List[str], model: str) -> List[List[float]]:
        if not texts:
            return []
        client = self._get_client()
        embed_model = model or "models/embedding-001"
        try:
            result = client.models.embed_content(
                model=embed_model,
                contents=texts,
            )
            if not hasattr(result, "embeddings") or not result.embeddings:
                raise ProviderError("Gemini returned no embeddings", provider="gemini")
            out = []
            for e in result.embeddings:
                if hasattr(e, "values"):
                    out.append(list(e.values))
                elif isinstance(e, (list, tuple)):
                    out.append(list(e))
                else:
                    out.append(list(getattr(e, "embedding", e)))
            return out
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"Gemini embed failed: {e}",
                provider="gemini",
                cause=e,
            )
