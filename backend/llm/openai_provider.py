"""
OpenAI provider with optional base_url and 429 retry.
"""
import os
import time
import logging
from typing import List, Dict, Any

from llm.provider_interface import LLMProvider, ProviderError

logger = logging.getLogger("btc_macro.llm.openai")

DEFAULT_MODEL = "gpt-4o"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 15


def _is_retryable(e: Exception) -> bool:
    err = str(e).lower()
    return "429" in str(e) or "rate" in err or "quota" in err


class OpenAIProvider(LLMProvider):
    """OpenAI API via openai SDK. Supports OPENAI_BASE_URL override."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            kwargs = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        temperature: float = 0,
        max_tokens: int = 256,
    ) -> str:
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
                        "OpenAI rate-limited (attempt %d/%d), waiting %ds",
                        attempt + 1, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                raise ProviderError(
                    f"OpenAI chat failed: {e}",
                    provider="openai",
                    cause=e,
                )
        raise ProviderError(
            f"OpenAI chat failed after {MAX_RETRIES} attempts: {last_error}",
            provider="openai",
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
                f"OpenAI embed failed: {e}",
                provider="openai",
                cause=e,
            )
