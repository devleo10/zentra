# .env File Configuration Issue

## Problem Detected
Your `.env` file appears to have the API keys mixed up. The error shows:
- `OPENAI_API_KEY` is set to your NewsAPI key value

## Fix Required

Please check your `backend/.env` file and ensure:

```env
OPENAI_API_KEY=sk-...your-actual-openai-key...
FRED_API_KEY=your-fred-key
NEWS_API_KEY=your-newsapi-key
```

**Important:**
- OpenAI API key should start with `sk-` 
- Make sure each key is on its own line
- No extra spaces or quotes around the values

## After Fixing

1. Run ingestion again:
   ```bash
   python -m rag.ingest
   ```

2. Start the server:
   ```bash
   python -m main
   ```


