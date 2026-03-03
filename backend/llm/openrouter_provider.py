"""
OpenRouter provider (OpenAI-compatible API with custom base URL).
"""
import os
import time
import logging
from typing import List, Dict, Any

from llm.provider_interface import LLMProvider, ProviderError

logger = logging.getLogger("btc_macro.llm.openrouter")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 15


def _is_retryable(e: Exception) -> bool:
    err = str(e).lower()
    return "429" in str(e) or "rate" in err or "quota" in err


class OpenRouterProvider(LLMProvider):
    """OpenRouter via OpenAI SDK with base_url and optional model override."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
    ):
        self._api_key = api_key
        self._base_url = (base_url or os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        temperature: float = 0,
        max_tokens: int = 256,
    ) -> str:
        # Allow env override for default model
        if not model or model == "gpt-4o":
            model = os.getenv("OPENROUTER_MODEL", model or "openai/gpt-4o")
        client = self._get_client()
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=messages,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                if _is_retryable(e) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE * (attempt + 1)
                    logger.warning(
                        "OpenRouter rate-limited (attempt %d/%d), waiting %ds",
                        attempt + 1, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                raise ProviderError(
                    f"OpenRouter chat failed: {e}",
                    provider="openrouter",
                    cause=e,
                )
        raise ProviderError(
            f"OpenRouter chat failed after {MAX_RETRIES} attempts: {last_error}",
            provider="openrouter",
            cause=last_error,
        )

    def embed(self, texts: List[str], model: str) -> List[List[float]]:
        if not texts:
            return []
        client = self._get_client()
        try:
            response = client.embeddings.create(model=model, input=texts)
            return [item.embedding for item in response.data]
        except Exception as e:
            raise ProviderError(
                f"OpenRouter embed failed: {e}",
                provider="openrouter",
                cause=e,
            )
