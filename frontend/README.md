# BTC Macro AI Agent - Frontend

## Setup Instructions

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure API URL

Create a `.env.local` file (optional, defaults to `http://localhost:8000`):

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Run Development Server

```bash
npm run dev
```

The dashboard will be available at `http://localhost:3000`

### 4. Build for Production

```bash
npm run build
npm start
```

## Features

- **7 Section Score Cards**: Individual scores for each checklist section
- **Score Gauge**: Visual 0-100 score display
- **Verdict Panel**: Final bias, action recommendation, and summary
- **Real-time Analysis**: Click "Run Analysis" to generate fresh analysis

## Project Structure

```
frontend/
├── app/                    # Next.js app directory
│   ├── page.tsx           # Main dashboard page
│   └── layout.tsx         # Root layout
├── components/             # React components
│   ├── ScoreCard.tsx      # Individual section card
│   ├── ScoreGauge.tsx     # Circular progress gauge
│   └── VerdictPanel.tsx   # Final verdict display
└── lib/                    # Utilities
    ├── api.ts             # API client
    └── utils.ts           # Helper functions
```


