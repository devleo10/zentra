"""
Centralized LLM provider abstraction (OpenAI only).

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

__all__ = [
    "LLMProvider",
    "ProviderError",
    "OpenAIProvider",
    "get_provider",
    "get_embedding_provider",
    "get_embeddings",
    "get_default_chat_model",
]
