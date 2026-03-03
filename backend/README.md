# BTC Macro AI Agent - Backend

## Setup Instructions

### 1. Install Dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set Up Environment Variables

Create a `.env` file in the `backend/` directory:

```env
OPENAI_API_KEY=your_openai_api_key_here
FRED_API_KEY=your_fred_api_key_here
NEWS_API_KEY=your_newsapi_key_here
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

**API Keys:**
- **OpenAI**: Required for OpenAI provider. Get from https://platform.openai.com
- **GEMINI_API_KEY**: Optional; used when `LLM_PROVIDER=gemini` or as fallback when OpenAI is not set.
- **FRED**: Free. Get from https://fred.stlouisfed.org/docs/api/api_key.html
- **NewsAPI**: Free tier available. Get from https://newsapi.org

**LLM provider (optional):**
- `LLM_PROVIDER=openai | gemini | openrouter` — which chat provider to use. If unset, defaults to OpenAI if `OPENAI_API_KEY` is set, else Gemini if `GEMINI_API_KEY` is set.
- `EMBEDDING_PROVIDER=openai | openrouter` — embeddings for RAG (default: openai). Falls back to Gemini if only `GEMINI_API_KEY` is set.
- `OPENAI_BASE_URL` — override OpenAI API base URL (e.g. for proxies).
- `OPENROUTER_BASE_URL` — default `https://openrouter.ai/api/v1`. Used when `LLM_PROVIDER=openrouter`.
- `OPENROUTER_API_KEY` — required for OpenRouter; can reuse `OPENAI_API_KEY` for some routes.
- `OPENROUTER_MODEL` — model name for OpenRouter (e.g. `openai/gpt-4o`).
- `OPENAI_MODEL`, `GEMINI_MODEL` — default chat model per provider.
- `OPENAI_EMBEDDING_MODEL` — default `text-embedding-3-small` for embeddings.

### 3. Ingest Knowledge Base

Before running the server, you need to ingest the knowledge base into ChromaDB:

```bash
python -m rag.ingest
```

This will:
- Load the 3 conversation files from `knowledge_base/`
- Chunk them into ~1000 token segments
- Embed using OpenAI embeddings
- Store in `chroma_db/` directory

### 4. Run the Server

**For the dashboard (recommended)** — use the v2 deterministic engine:

```bash
python -m main_v2
```

Or using uvicorn:

```bash
uvicorn main_v2:app --reload --port 8000
```

**Legacy v1 API only** (no `/api/v2/*` endpoints):

```bash
python -m main
```

The API will be available at `http://localhost:8000`

## API Endpoints

- `GET /` - API information
- `POST /api/analyze` - Run full 7-section analysis
- `GET /api/analyze/{section}` - Run single section (inflation, fed, liquidity, dxy, risk, bitcoin)
- `GET /api/health` - Health check

## Project Structure

```
backend/
├── main.py                 # FastAPI app
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (create this)
├── knowledge_base/         # Source conversation files
├── rag/                    # RAG pipeline
├── data_fetchers/          # API data fetchers
├── agents/                 # Analysis agents
└── models/                 # Pydantic schemas
```


