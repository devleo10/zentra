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
ALPHAVANTAGE_API_KEY=your_alphavantage_api_key_here
FINNHUB_API_KEY=your_finnhub_api_key_here
FMP_API_KEY=your_fmp_api_key_here
EODHD_API_TOKEN=your_eodhd_api_token_here
TRADINGECONOMICS_API_KEY=your_te_user_colon_password
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

**API Keys:**
- **OpenAI** (`OPENAI_API_KEY`): Required for LLM and embeddings. Get from https://platform.openai.com
- **FRED**: Free. Get from https://fred.stlouisfed.org/docs/api/api_key.html
- **NewsAPI**: Free tier available. Get from https://newsapi.org. When set, headlines are also fetched from **Reuters**, **Financial Times**, and **Stratfor** (via the `domains` parameter). Stratfor may return no results if not indexed by NewsAPI.
- **Alpha Vantage** (`ALPHAVANTAGE_API_KEY`): Optional. Used for ISM/PMI fallback and NEWS_SENTIMENT fallback.
- **Finnhub** (`FINNHUB_API_KEY`): Optional. Used for macro headline fallback.
- **FMP** (`FMP_API_KEY`): Optional. Trusted market fallback for MOVE, VIX, S&P 500, EEM, BTC ETF volume.
- **EODHD** (`EODHD_API_TOKEN`): Optional. Trusted market fallback for MOVE, VIX, S&P 500, EEM.
- **TradingEconomics** (`TRADINGECONOMICS_API_KEY`): Optional. Trusted market fallback for VIX and S&P 500. Format is usually `user:password`; if omitted the app uses guest mode where available.

**Optional env (OpenAI):**
- `OPENAI_BASE_URL` — override API base URL (e.g. for proxies).
- `OPENAI_MODEL` — default chat model (default: `gpt-4o`).
- `OPENAI_EMBEDDING_MODEL` — default `text-embedding-3-small` for RAG embeddings.

**Optional env (monthly performance):**
- `ENABLE_MONTHLY_METRIC_CACHE` — default `1`. When enabled, `timeframe=month` runs reuse persisted slow macro metrics.
- `MONTHLY_SLOW_METRIC_CACHE_TTL_SECONDS` — default `43200` (12h). Controls cache freshness window for those slow monthly metrics.

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

## Accuracy Audit / TradingView Cross-Check

Run a full analysis and compare key metrics to TradingView references:

```bash
python scripts/tradingview_crosscheck_report.py --timeframe month --fresh
```

Reports are written to `backend/logs/` as both `.json` and `.md` files.

## Render Keep-Warm

The repository includes `.github/workflows/render-keepalive.yml`.

1. Add GitHub Actions secret `KEEPALIVE_URL` with your deployed backend keepalive endpoint, for example:
	`https://<your-service>.onrender.com/api/keepalive`
2. The workflow pings every 10 minutes to reduce free-plan cold starts.

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


