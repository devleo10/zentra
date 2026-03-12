"""
Central factory for LLM and embedding providers.

OpenAI only: requires OPENAI_API_KEY. Chat and embeddings both use OpenAI.
"""
import os
import logging

from dotenv import load_dotenv

load_dotenv()

from llm.provider_interface import LLMProvider, ProviderError
from llm.openai_provider import OpenAIProvider
from llm.embeddings_adapter import LangChainEmbeddingsAdapter

logger = logging.getLogger("btc_macro.llm.factory")


def get_provider() -> LLMProvider:
    """
    Return the configured chat LLM provider (OpenAI only).

    Requires OPENAI_API_KEY in environment.

    Raises:
        ValueError: If OPENAI_API_KEY is not set.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError(
            "No LLM provider configured. Set OPENAI_API_KEY in backend/.env"
        )
    return OpenAIProvider(api_key=key)


def get_embedding_provider() -> LLMProvider:
    """
    Return the provider used for embeddings (OpenAI only).
    """
    return get_provider()


def get_default_chat_model() -> str:
    """Return the default chat model (OpenAI)."""
    return os.getenv("OPENAI_MODEL", "gpt-4o")


def get_embeddings():
    """
    Return a LangChain-compatible Embeddings object for RAG (FAISS, retriever).

    Uses OPENAI_API_KEY and OPENAI_EMBEDDING_MODEL.
    """
    provider = get_embedding_provider()
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    return LangChainEmbeddingsAdapter(provider, model)
