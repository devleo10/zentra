"""
Ingest knowledge base documents into FAISS vector store
"""
import os
import pickle
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()

# Configuration
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
PERSIST_DIRECTORY = Path(__file__).parent.parent / "faiss_db"
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge_base"


def ingest_knowledge_base():
    """Chunk, embed, and store knowledge base documents in FAISS"""
    
    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    
    # Initialize embeddings
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    # Load documents
    documents = []
    doc_files = [
        "chat1_money_rotation.txt",
        "chat2_btc_macro_analysis.txt",
        "chat3_macro_geopolitics.txt"
    ]
    
    for doc_file in doc_files:
        file_path = KNOWLEDGE_BASE_DIR / doc_file
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                documents.append({
                    'content': content,
                    'metadata': {'source': doc_file}
                })
        else:
            print(f"Warning: {doc_file} not found")
    
    if not documents:
        raise ValueError("No documents found in knowledge_base directory")
    
    # Split documents into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    
    texts = []
    metadatas = []
    
    for doc in documents:
        chunks = text_splitter.split_text(doc['content'])
        texts.extend(chunks)
        metadatas.extend([doc['metadata']] * len(chunks))
    
    print(f"Created {len(texts)} chunks from {len(documents)} documents")
    
    # Create vector store
    vectorstore = FAISS.from_texts(
        texts=texts,
        metadatas=metadatas,
        embedding=embeddings
    )
    
    # Persist to disk
    PERSIST_DIRECTORY.mkdir(exist_ok=True)
    vectorstore.save_local(str(PERSIST_DIRECTORY))
    print(f"Vector store persisted to {PERSIST_DIRECTORY}")
    
    return vectorstore


if __name__ == "__main__":
    print("Starting knowledge base ingestion...")
    vectorstore = ingest_knowledge_base()
    print("Ingestion complete!")

