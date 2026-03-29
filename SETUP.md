# BTC Macro AI Agent - Complete Setup Guide

## Overview

This is a full-stack AI agentic system that analyzes Bitcoin through macroeconomic, geopolitical, and Federal Reserve policy lenses. The system uses RAG (Retrieval Augmented Generation) with LangChain to analyze real-time market data against a knowledge base of money rotation and Bitcoin macro analysis frameworks.

## Architecture

- **Backend**: Python FastAPI + LangChain + OpenAI GPT-4o
- **Frontend**: Next.js 14 + TypeScript + Tailwind CSS
- **Knowledge Base**: 3 ChatGPT conversations stored in ChromaDB
- **Data Sources**: FRED API, Yahoo Finance, CoinGecko, NewsAPI, and optional trusted market APIs (FMP, EODHD, TradingEconomics)

## Prerequisites

- Python 3.10+
- Node.js 18+
- API Keys:
  - OpenAI API key (required)
  - FRED API key (free)
  - NewsAPI key (free tier)
  - FMP API key (optional trusted market fallback)
  - EODHD API token (optional trusted market fallback)
  - TradingEconomics credential (optional trusted market fallback; usually `user:password`)

## Quick Start

### 1. Backend Setup

```bash
# Navigate to backend
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env and add your API keys

# Ingest knowledge base
python -m rag.ingest

# Run server
python -m main
```

Backend will run on `http://localhost:8000`

### 2. Frontend Setup

```bash
# Navigate to frontend (in a new terminal)
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

Frontend will run on `http://localhost:3000`

## Project Structure

```
Crypto/
├── backend/                    # Python FastAPI backend
│   ├── main.py                 # FastAPI app
│   ├── requirements.txt        # Python dependencies
│   ├── knowledge_base/         # 3 conversation files
│   ├── rag/                    # RAG pipeline
│   ├── data_fetchers/          # API data fetchers
│   ├── agents/                  # 7 analysis agents
│   └── models/                  # Pydantic schemas
├── frontend/                   # Next.js dashboard
│   ├── app/                     # Next.js app directory
│   ├── components/              # React components
│   └── lib/                     # Utilities
├── context.md                  # Knowledge base source
├── Daily_Bitcoin_Macro_Checklist.md
└── IMPLEMENTATION_PLAN.md
```

## API Endpoints

- `GET /` - API information
- `POST /api/analyze` - Run full 7-section analysis
- `GET /api/analyze/{section}` - Run single section
- `GET /api/health` - Health check

## How It Works

1. **Data Collection**: Each agent fetches real-time data from APIs (FRED, Yahoo Finance, CoinGecko, NewsAPI)
2. **Knowledge Retrieval**: Agents query the RAG knowledge base for relevant frameworks and scoring methodologies
3. **Analysis**: GPT-4o analyzes the data against the knowledge base frameworks
4. **Scoring**: Each section receives a 0-100 score with reasoning
5. **Verdict**: Final weighted score (0-100) determines bias (Bullish/Neutral/Bearish) and action recommendation

## The 7 Analysis Sections

1. **Inflation & Economy** (20% weight) - CPI, PCE, PMI, GDP
2. **Federal Reserve Signals** (25% weight) - Fed speeches, keyword analysis
3. **Liquidity & Bonds** (20% weight) - Treasury yields, Fed balance sheet
4. **US Dollar (DXY)** (20% weight) - Dollar strength, BTC correlation
5. **Risk Sentiment** (15% weight) - VIX, S&P 500, Gold
6. **Bitcoin Focus** - BTC price, dominance, stablecoins, ETH/BTC
7. **Final Bias** - Weighted aggregation of all scores

## Troubleshooting

### Backend Issues

- **"Vector store not found"**: Run `python -m rag.ingest` first
- **"API key not found"**: Check your `.env` file in `backend/` directory
- **Import errors**: Make sure you're in the virtual environment and dependencies are installed

### Frontend Issues

- **"Cannot connect to API"**: Ensure backend is running on port 8000
- **Build errors**: Run `npm install` again and check Node.js version (18+)

## Next Steps

1. Set up your API keys in `backend/.env`
2. Ingest the knowledge base: `python -m rag.ingest`
3. Start backend: `python -m main`
4. Start frontend: `npm run dev`
5. Open `http://localhost:3000` and click "Run Analysis"

## License

This project is for educational purposes.


