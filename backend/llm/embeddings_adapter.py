"""
LangChain-compatible Embeddings adapter that uses LLMProvider.embed().

Allows RAG (FAISS, retriever) to use the centralized embedding provider.
"""
import logging
from typing import List

from langchain_core.embeddings import Embeddings
from llm.provider_interface import LLMProvider

logger = logging.getLogger("btc_macro.llm.embeddings")


class LangChainEmbeddingsAdapter(Embeddings):
    """Wraps an LLMProvider for use as LangChain Embeddings (embed_documents, embed_query)."""

    def __init__(self, provider: LLMProvider, model: str):
        self._provider = provider
        self._model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        return self._provider.embed(texts, self._model)

    def embed_query(self, text: str) -> List[float]:
        if not text:
            return []
        return self._provider.embed([text], self._model)[0]

    def __call__(self, text: str) -> List[float]:
        """
        Backward-compatible callable interface for older FAISS integrations
        that still call embedding_function(text) directly.
        """
        return self.embed_query(text)
