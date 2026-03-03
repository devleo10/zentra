"""
Centralized LLM provider abstraction.

- LLMProvider: base interface (chat, embed)
- get_provider(), get_embedding_provider(), get_embeddings(), get_default_chat_model()
- ProviderError for structured errors
"""
from llm.provider_interface import LLMProvider, ProviderError
from llm.provider_factory import (
    get_provider,
    get_embedding_provider,
    get_embeddings,
    get_default_chat_model,
)
from llm.openai_provider import OpenAIProvider
from llm.gemini_provider import GeminiProvider
from llm.openrouter_provider import OpenRouterProvider

__all__ = [
    "LLMProvider",
    "ProviderError",
    "OpenAIProvider",
    "GeminiProvider",
    "OpenRouterProvider",
    "get_provider",
    "get_embedding_provider",
    "get_embeddings",
    "get_default_chat_model",
]
