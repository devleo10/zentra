"""
Retrieve relevant chunks from FAISS vector store
"""
import os
from pathlib import Path
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()

PERSIST_DIRECTORY = Path(__file__).parent.parent / "faiss_db"


def get_retriever(k=5):
    """
    Get a retriever from the FAISS vector store
    
    Args:
        k: Number of documents to retrieve
        
    Returns:
        Retriever object
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    
    if not PERSIST_DIRECTORY.exists():
        raise ValueError(
            f"Vector store not found at {PERSIST_DIRECTORY}. "
            "Run ingest.py first to create the vector store."
        )
    
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
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
    docs = retriever.get_relevant_documents(query)
    return docs

