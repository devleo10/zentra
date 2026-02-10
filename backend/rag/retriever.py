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
    """Get embeddings - try Gemini first, fallback to OpenAI"""
    # Try Gemini first
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model="models/gemini-embedding-001",
                google_api_key=gemini_key
            )
        except ImportError:
            try:
                from langchain_community.embeddings import GooglePalmEmbeddings
                return GooglePalmEmbeddings(google_api_key=gemini_key)
            except ImportError:
                pass
    
    # Fallback to OpenAI
    from langchain_openai import OpenAIEmbeddings
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("Neither GEMINI_API_KEY nor OPENAI_API_KEY found in environment variables")
    return OpenAIEmbeddings(model="text-embedding-3-small")


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

