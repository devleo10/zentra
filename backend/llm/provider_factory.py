"""
Central factory for LLM and embedding providers.

- LLM_PROVIDER=openai | gemini | openrouter (default: infer from keys)
- EMBEDDING_PROVIDER=openai | openrouter (default: openai)
- Preserves existing behavior: if LLM_PROVIDER not set, use OPENAI_API_KEY then GEMINI_API_KEY.
"""
import os
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from llm.provider_interface import LLMProvider, ProviderError
from llm.openai_provider import OpenAIProvider
from llm.gemini_provider import GeminiProvider
from llm.openrouter_provider import OpenRouterProvider
from llm.embeddings_adapter import LangChainEmbeddingsAdapter

logger = logging.getLogger("btc_macro.llm.factory")


def _resolve_chat_provider() -> str:
    """Resolve which chat provider to use from env."""
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit in ("openai", "gemini", "openrouter"):
        return explicit
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return ""


def _resolve_embedding_provider() -> str:
    """Resolve which embedding provider to use. Only openai or openrouter."""
    explicit = (os.getenv("EMBEDDING_PROVIDER") or "").strip().lower()
    if explicit == "openrouter":
        if os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"):
            return "openrouter"
        logger.warning("EMBEDDING_PROVIDER=openrouter but no OPENROUTER_API_KEY/OPENAI_API_KEY; defaulting to openai")
    return "openai"


def get_provider() -> LLMProvider:
    """
    Return the configured chat LLM provider.

    Selection: LLM_PROVIDER env, else OPENAI_API_KEY -> openai, else GEMINI_API_KEY -> gemini,
    else OPENROUTER_API_KEY -> openrouter.

    Raises:
        ValueError: If no provider can be configured.
    """
    kind = _resolve_chat_provider()
    if kind == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIProvider(api_key=key)
    if kind == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY and OPENAI_API_KEY are not set"
            )
        return OpenRouterProvider(api_key=key)
    if kind == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return GeminiProvider(api_key=key)
    raise ValueError(
        "No LLM provider configured. Set LLM_PROVIDER (openai|gemini|openrouter) or set "
        "OPENAI_API_KEY or GEMINI_API_KEY in backend/.env"
    )


def get_embedding_provider() -> LLMProvider:
    """
    Return the provider used only for embeddings (openai or openrouter).

    EMBEDDING_PROVIDER=openai | openrouter; default openai.
    If OPENAI_API_KEY is not set, falls back to Gemini when GEMINI_API_KEY is set (preserves prior behavior).
    """
    kind = _resolve_embedding_provider()
    if kind == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                "EMBEDDING_PROVIDER=openrouter but OPENROUTER_API_KEY/OPENAI_API_KEY not set"
            )
        return OpenRouterProvider(api_key=key)
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return OpenAIProvider(api_key=key)
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        return GeminiProvider(api_key=gemini_key)
    raise ValueError(
        "Embeddings require OPENAI_API_KEY or GEMINI_API_KEY "
        "(or set EMBEDDING_PROVIDER=openrouter and OPENROUTER_API_KEY)"
    )


def get_default_chat_model() -> str:
    """Return the default chat model for the current provider (for agents, etc.)."""
    kind = _resolve_chat_provider()
    if kind == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o")
    if kind == "openrouter":
        return os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")
    if kind == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    return "gpt-4o"


def get_embeddings():
    """
    Return a LangChain-compatible Embeddings object for RAG (FAISS, retriever).

    Uses EMBEDDING_PROVIDER (default openai) and OPENAI_EMBEDDING_MODEL.
    For Gemini fallback, uses models/embedding-001.
    """
    provider = get_embedding_provider()
    if isinstance(provider, GeminiProvider):
        model = os.getenv("GEMINI_EMBEDDING_MODEL", "models/embedding-001")
    else:
        model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    return LangChainEmbeddingsAdapter(provider, model)
