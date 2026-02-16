"""
Retrieve relevant chunks from FAISS vector store
"""
import os
from pathlib import Path
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()

PERSIST_DIRECTORY = Path(__file__).parent.parent / "faiss_db"


def get_embeddings():
    """Get embeddings - prefer OpenAI, optionally use Gemini as fallback"""
    # Prefer OpenAI embeddings when available
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
        except Exception:
            # If langchain_openai isn't installed, fall through to try Gemini
            pass

    # Try Gemini/Google embeddings if OpenAI isn't configured or failed
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model="models/gemini-embedding-001",
                google_api_key=gemini_key
            )
        except Exception:
            try:
                from langchain_community.embeddings import GooglePalmEmbeddings
                return GooglePalmEmbeddings(google_api_key=gemini_key)
            except Exception:
                pass

    raise ValueError("No embeddings available: set OPENAI_API_KEY or GEMINI_API_KEY in environment variables")


def get_retriever(k=5):
    """
    Get a retriever from the FAISS vector store
    
    Args:
        k: Number of documents to retrieve
        
    Returns:
        Retriever object
    """
    if not PERSIST_DIRECTORY.exists():
        raise ValueError(
            f"Vector store not found at {PERSIST_DIRECTORY}. "
            "Run ingest.py first to create the vector store."
        )
    
    embeddings = get_embeddings()
    
    vectorstore = FAISS.load_local(
        str(PERSIST_DIRECTORY),
        embeddings,
        allow_dangerous_deserialization=True
    )
    
    retriever = vectorstore.as_retriever(
        search_kwargs={"k": k}
    )
    
    return retriever


def retrieve_relevant_chunks(query: str, k: int = 5):
    """
    Retrieve relevant chunks for a query
    
    Args:
        query: Search query
        k: Number of chunks to retrieve
        
    Returns:
        List of relevant document chunks
    """
    retriever = get_retriever(k=k)
    # Use invoke() for newer LangChain versions
    docs = retriever.invoke(query)
    return docs

