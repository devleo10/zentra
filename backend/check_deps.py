"""Check if dependencies are installed"""
import sys

deps = {
    "fastapi": "FastAPI",
    "langchain": "LangChain",
    "chromadb": "ChromaDB",
    "yfinance": "yfinance",
    "openai": "OpenAI",
    "pydantic": "Pydantic"
}

print("Checking dependencies...")
missing = []
for module, name in deps.items():
    try:
        __import__(module)
        print(f"[OK] {name}: INSTALLED")
    except ImportError:
        print(f"[MISSING] {name}: NOT INSTALLED")
        missing.append(name)

if missing:
    print(f"\nMissing: {', '.join(missing)}")
    print("Run: pip install -r requirements.txt")
else:
    print("\nAll dependencies installed!")

