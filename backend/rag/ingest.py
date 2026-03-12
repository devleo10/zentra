"""
Ingest knowledge base documents into FAISS vector store.

Uses centralized llm.get_embeddings() (OpenAI).
"""
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()

# Configuration
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
PERSIST_DIRECTORY = Path(__file__).parent.parent / "faiss_db"
KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge_base"


def get_embeddings():
    """LangChain-compatible embeddings via llm factory (OpenAI)."""
    try:
        from llm import get_embeddings as _get_embeddings
    except ImportError:
        from llm.provider_factory import get_embeddings as _get_embeddings
    return _get_embeddings()


def ingest_knowledge_base():
    """Chunk, embed, and store knowledge base documents in FAISS"""
    
    # Initialize embeddings (OpenAI)
    embeddings = get_embeddings()
    
    # Load documents - try knowledge_base directory first, then context.md
    documents = []
    
    # Try knowledge_base directory
    if KNOWLEDGE_BASE_DIR.exists():
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
    
    # Fallback to context.md if knowledge_base doesn't exist or is empty
    if not documents:
        context_file = Path(__file__).parent.parent / "context.md"
        if context_file.exists():
            print(f"Using context.md as knowledge base...")
            with open(context_file, 'r', encoding='utf-8') as f:
                content = f.read()
                documents.append({
                    'content': content,
                    'metadata': {'source': 'context.md'}
                })
    
    if not documents:
        raise ValueError("No documents found. Please ensure context.md exists or knowledge_base directory has files.")
    
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

