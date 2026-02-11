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
- **OpenAI**: Required. Get from https://platform.openai.com
- **FRED**: Free. Get from https://fred.stlouisfed.org/docs/api/api_key.html
- **NewsAPI**: Free tier available. Get from https://newsapi.org

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

```bash
python -m main
```

Or using uvicorn directly:

```bash
uvicorn main:app --reload --port 8000
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


