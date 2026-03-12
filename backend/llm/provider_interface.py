"""
Base interface and errors for LLM providers.

All providers implement chat() and embed() with a consistent interface.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class ProviderError(Exception):
    """Raised when an LLM provider call fails (after retries)."""

    def __init__(self, message: str, provider: str = "", cause: Optional[Exception] = None):
        self.provider = provider
        self.cause = cause
        super().__init__(message)


class LLMProvider(ABC):
    """Abstract base for LLM providers (OpenAI implementation)."""

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        *,
        temperature: float = 0,
        max_tokens: int = 256,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send messages and return the assistant reply text.

        Args:
            messages: List of {"role": "user"|"system"|"assistant", "content": str}
            model: Model name (e.g. gpt-4o)
            temperature: Sampling temperature
            max_tokens: Max response tokens
            response_format: Optional structured output hint (provider-specific).

        Returns:
            Assistant content string.

        Raises:
            ProviderError: On API or rate-limit failure after retries.
        """
        pass

    @abstractmethod
    def embed(self, texts: List[str], model: str) -> List[List[float]]:
        """
        Embed texts and return list of embedding vectors.

        Args:
            texts: Input strings to embed
            model: Embedding model name

        Returns:
            List of embedding vectors (each a list of floats).

        Raises:
            ProviderError: On API failure.
        """
        pass
