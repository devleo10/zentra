You are acting as a senior quantitative macro systems engineer.

I have a BTC Macro AI Agent Dashboard that runs locally on a client’s laptop.
It is NOT hosted.
It is executed manually twice per day.
It currently relies mostly on macro numeric indicators (CPI, DXY, VIX, 10Y yield, liquidity, etc.).
The client reports that it is “not working as expected” and wants it to also consider important U.S. macro headlines (e.g., FOMC decisions, Fed speeches, major economic events).

Your task is to redesign and refactor this system to be:

1. Deterministic
2. Reproducible
3. Local-first (no cloud infra assumptions)
4. Robust against API failures
5. Historically auditable
6. Context-aware using macro headlines
7. Transparent in logic (no hidden black-box scoring)

You must provide:

- Architecture structure
- Folder structure
- Database schema
- Scoring logic
- Headline ingestion logic
- LLM usage pattern (deterministic)
- Error handling approach
- Data freshness handling
- How final bias is computed
- How headline-based adjustments affect score
- Safeguards against LLM randomness
- Example Python pseudocode

---------------------------------------
SECTION 1 — ARCHITECTURE
---------------------------------------

Design a clean local architecture:

- run_analysis.py entry point
- data_fetchers/
- scoring_engine/
- headline_engine/
- llm_client/
- storage/
- config/

Explain responsibilities of each module.

---------------------------------------
SECTION 2 — DATABASE (LOCAL)
---------------------------------------

Design a SQLite schema with:

Table: macro_snapshots
- id
- timestamp
- cpi
- dxy
- vix
- ten_year_yield
- fed_balance_sheet
- btc_price
- section_scores (JSON)
- macro_event_score
- final_score
- bias
- confidence
- data_freshness_info (JSON)

Explain why each field exists.

---------------------------------------
SECTION 3 — NUMERIC SCORING ENGINE
---------------------------------------

Refactor scoring logic to be 100% deterministic.

- No LLM involvement in numeric scoring.
- Use explicit threshold or z-score rules.
- No random components.
- All weights stored in config file.

Provide example scoring formula.

---------------------------------------
SECTION 4 — HEADLINE INGESTION
---------------------------------------

Add macro headline ingestion:

- Use NewsAPI or similar.
- Fetch last 24-48 hours only.
- Filter by keywords:
  "Federal Reserve", "FOMC", "Interest Rate", 
  "Inflation", "CPI", "Treasury", 
  "Debt Ceiling", "Jobs Report", "Nonfarm Payrolls"

Design filtering pipeline.

---------------------------------------
SECTION 5 — HEADLINE CLASSIFICATION
---------------------------------------

Use LLM ONLY for headline classification.

Rules:
- temperature = 0
- Strict JSON output
- No narrative
- Validate output schema

Return JSON:
{
  "event_bias": "hawkish | dovish | neutral",
  "risk_impact": "risk_on | risk_off | neutral",
  "confidence": 0-1,
  "reason": "short explanation"
}

Show exact prompt template.

---------------------------------------
SECTION 6 — EVENT SCORE INTEGRATION
---------------------------------------

Design deterministic rule:

If hawkish + risk_off → subtract X points.
If dovish + risk_on → add Y points.
If neutral → no change.

Make adjustment capped (e.g., max ±10).

Ensure headline cannot fully override numeric macro engine.

---------------------------------------
SECTION 7 — DATA FRESHNESS SAFETY
---------------------------------------

Add data staleness validation:

- CPI older than 35 days → warn.
- BTC price older than 10 minutes → warn.
- Yields older than 1 day → warn.

System must refuse to compute final verdict if critical data missing.

---------------------------------------
SECTION 8 — ERROR HANDLING
---------------------------------------

- Wrap all API calls in try/except.
- If API fails:
    - Log error
    - Do NOT silently default to 50 score.
    - Stop execution with meaningful message.
- Add logging to file.

---------------------------------------
SECTION 9 — FINAL VERDICT LOGIC
---------------------------------------

Design clear rule:

final_score = weighted_numeric_score + macro_event_adjustment

Bias:
>70 → Bullish
40-70 → Neutral
<40 → Bearish

Confidence:
Based on:
- Agreement between sections
- Magnitude of final_score distance from 50
- Headline confidence score

Provide deterministic formula.

---------------------------------------
SECTION 10 — REPRODUCIBILITY
---------------------------------------

Ensure:

- Same input → same output.
- No randomness.
- All configs versioned.
- Prompt version stored.
- LLM model version stored.

---------------------------------------
SECTION 11 — EXAMPLE PSEUDOCODE
---------------------------------------

Provide simplified Python pseudocode for:

run_analysis()

Including:

- Fetch numeric data
- Validate freshness
- Compute numeric score
- Fetch headlines
- Classify headlines via LLM
- Compute adjustment
- Store snapshot
- Print final result

---------------------------------------
SECTION 12 — COMMON FAILURE SCENARIOS
---------------------------------------

List at least 8 realistic failure cases and how system handles them.

---------------------------------------

Be technical.
Be precise.
No vague suggestions.
Assume this will run locally twice per day.
No cloud infrastructure.
No streaming.
No auto-trading.
No overengineering.
Focus on robustness and correctness.

