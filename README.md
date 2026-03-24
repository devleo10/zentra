# Zentra — Bitcoin macro analysis

Full-stack app that scores Bitcoin macro conditions using live data (FRED, Yahoo Finance, news), a deterministic scoring engine, and optional LLM layers (classification, Fed tone, narrative). **Not financial advice.** Data and labels depend on third-party feeds and chosen time windows (for example MTD vs rolling month).

## Stack

- **Backend:** Python 3.10+, FastAPI (`main_v2`), SQLite snapshots, RAG (Chroma + OpenAI embeddings)
- **Frontend:** Next.js 14, TypeScript, Tailwind

## Prerequisites

- Python 3.10+ and Node.js 18+
- **OpenAI** API key (LLM + embeddings)
- **FRED** API key (free)
- **NewsAPI** key (optional; improves headline coverage)

## Environment

**`backend/.env`** (create from scratch; do not commit):

```env
OPENAI_API_KEY=
FRED_API_KEY=
NEWS_API_KEY=
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

Optional: `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`.

**`frontend/.env.local`** (optional):

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Quick start

### Backend

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m rag.ingest   # builds the local Chroma index from knowledge_base/; re-run after editing those files
python -m main_v2
```

API base: `http://localhost:8000`  
**`main_v2`** is the supported entrypoint (dashboard uses `/api/v2/*`). **`main`** remains for legacy `/api/analyze` routes.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: `http://localhost:3000`

### Windows

You can use `start.bat` / `setup_and_run.bat` in the repo root if you already use them; ensure `backend/.env` exists first.

## Main API (v2)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v2/analyze` | Run analysis |
| GET | `/api/v2/analyze/{timeframe}` | Analysis for a timeframe |
| GET | `/api/v2/analyze/compare` | Compare runs |
| GET | `/api/v2/history` | List snapshots |
| GET | `/api/v2/history/{snapshot_id}` | One snapshot |
| GET | `/api/v2/config` | Effective config |
| GET | `/api/health` | Health |

## Project layout

```
backend/   FastAPI, agents, data_fetchers, scoring_engine, rag/, storage/
frontend/  Next.js app, components, lib/api.ts
```

SQLite snapshots live under `backend/storage/` (see `storage/db.py`).

## License

Educational / personal use unless you add your own terms.
