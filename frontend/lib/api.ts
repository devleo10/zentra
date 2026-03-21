/**
 * API client for backend — v2 (Deterministic Engine) + Legacy v1
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export type TimeFrame = "current" | "week" | "month"

// ── v2 Types (Deterministic Engine) ──────────────────────────────────────

export interface V2SectionScores {
  inflation: number
  economy: number
  fed_policy: number
  liquidity: number
  dxy: number
  risk_sentiment: number
}

export interface V2HeadlineClassification {
  event_bias: "hawkish" | "dovish" | "neutral"
  risk_impact: "risk_on" | "risk_off" | "neutral"
  confidence: number
  reason: string
}

export interface V2AnalysisResult {
  timestamp: string
  btc_price: number | null
  section_scores: V2SectionScores
  section_reasoning: Record<string, string>
  weighted_numeric_score: number
  score_breakdown: Record<string, number>
  headlines_fetched: number
  headlines_classified: V2HeadlineClassification[]
  headline_adjustment: number
  headline_reasoning: string
  final_score: number
  bias: string
  action: string
  confidence_pct: number
  confidence_label: string
  data_freshness_info: {
    can_proceed: boolean
    checks: Array<{
      name: string
      status: string
      data_date: string | null
      age: string | null
      is_critical: boolean
    }>
    warnings: string[]
    critical_failures: string[]
  }
  config_hash: string
  prompt_version: string
  llm_model: string
  fed_tone?: "hawkish" | "dovish" | "neutral"
  dovish_keyword_count: number
  hawkish_keyword_count: number
  pivot_keyword_count: number
  cpi_mom_change: number | null
  cpi_yoy_rate: number | null
  cpi_core_yoy_rate: number | null
  cpi_trend: string | null
  cpi_mom_avg_3m: number | null
  cpi_mom_avg_3m_prior: number | null
  cpi_mom_avg_3m_trend: string | null
  dxy_value: number | null
  dxy_change_7d: number | null
  dxy_trend: string | null
  vix: number | null
  ten_year_yield: number | null
  ten_year_yield_trend: string | null
  oil_price: number | null
  oil_change: number | null
  oil_trend: string | null
  cross_signal_adjustment: number
  cross_signal_reasoning: string
  narrative: string
  key_risk: string
  catalyst_to_watch: string
  // Economy indicators
  unemployment_rate: number | null
  unemployment_trend: string | null
  unemployment_trend_mom: string | null
  unemployment_trend_3m: string | null
  unemployment_3m_avg: number | null
  unemployment_history_3: Array<{ date: string; rate: number }> | null
  nfp_change: number | null
  gdp_growth_rate: number | null
  gdp_trend: string | null
  pmi_value: number | null
  pmi_status: string | null
  pmi_trend: string | null
  m2_trend: string | null
  m2_change: number | null
  m2_yoy_change: number | null
  // Gold & VIX trends
  sp500_price: number | null
  sp500_change: number | null
  sp500_trend: string | null
  gold_price: number | null
  gold_change: number | null
  gold_trend: string | null
  vix_change: number | null
  vix_trend: string | null
  // Bond market
  two_year_yield: number | null
  two_year_yield_trend: string | null
  yield_curve_spread: number | null
  yield_monthly_track: Array<{ date: string; yield_10y: number; yield_2y: number; spread: number }> | null
  yield_spread_delta_3m: number | null
  yield_spread_trend_3m: string | null
  yield_10y_delta_3m: number | null
  yield_2y_delta_3m: number | null
  // Fed stance
  fed_funds_rate: number | null
  fed_rate_trend: string | null
  fed_rate_stance: string | null
  fed_rate_type?: string | null
  // Natural gas
  natgas_price: number | null
  natgas_change: number | null
  natgas_trend: string | null
  move_index_value: number | null
  move_index_change: number | null
  move_index_trend: string | null
  eem_price: number | null
  eem_change: number | null
  eem_trend: string | null
  // BTC market structure
  btc_dominance: number | null
  stablecoin_dominance: number | null
  btc_ma200: number | null
  btc_realized_vol_30d: number | null
  btc_etf_volume: number | null
  btc_etf_flow_level: string | null
  btc_market_arrow: "up" | "down" | null
  // DXY structure
  dxy_structure: string | null
  // Geopolitics
  geopolitics_risk_level: string | null
  // Top headlines for display (matched_* from backend when available)
  top_headlines: Array<{
    title: string
    source: string
    event_bias: string
    risk_impact: string
    confidence: number
    matched_hawkish?: string[]
    matched_dovish?: string[]
  }>
}

export interface V2HistoryEntry extends V2AnalysisResult {
  id: number
}

// ── v2 API Calls ─────────────────────────────────────────────────────────

export async function runV2Analysis(timeframe: TimeFrame = "current"): Promise<V2AnalysisResult> {
  const response = await fetch(`${API_BASE_URL}/api/v2/analyze/${timeframe}`)

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`v2 Analysis failed: ${response.statusText} — ${errorText}`)
  }

  return response.json()
}

export async function getV2History(limit: number = 10): Promise<V2HistoryEntry[]> {
  const response = await fetch(`${API_BASE_URL}/api/v2/history?limit=${limit}`)
  if (!response.ok) {
    throw new Error(`History fetch failed: ${response.statusText}`)
  }
  return response.json()
}

export async function getV2Config(): Promise<Record<string, any>> {
  const response = await fetch(`${API_BASE_URL}/api/v2/config`)
  if (!response.ok) {
    throw new Error(`Config fetch failed: ${response.statusText}`)
  }
  return response.json()
}

// ── Legacy v1 Types ──────────────────────────────────────────────────────

export interface SectionScore {
  name: string
  score: number
  signals: string[]
  reasoning: string
  data_used?: Record<string, any>
}

export interface VerdictResponse {
  timestamp: string
  timeframe: TimeFrame
  sections: SectionScore[]
  final_score: number
  bias: string
  action: string
  confidence: string
  summary: string
}

export interface AnalysisRequest {
  sections?: string[]
  timeframe?: TimeFrame
}

// ── Legacy v1 API Calls ──────────────────────────────────────────────────

export async function runAnalysis(timeframe: TimeFrame = "current"): Promise<VerdictResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ timeframe }),
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Analysis failed: ${response.statusText} - ${errorText}`)
  }

  return response.json()
}

export async function runDemoAnalysis(): Promise<VerdictResponse> {
  const response = await fetch(`${API_BASE_URL}/api/demo`)
  if (!response.ok) {
    throw new Error(`Demo analysis failed: ${response.statusText}`)
  }
  return response.json()
}

export async function analyzeSection(section: string, timeframe: TimeFrame = "current"): Promise<SectionScore> {
  const response = await fetch(`${API_BASE_URL}/api/analyze/${section}?timeframe=${timeframe}`)
  if (!response.ok) {
    throw new Error(`Section analysis failed: ${response.statusText}`)
  }
  return response.json()
}

export async function healthCheck() {
  const response = await fetch(`${API_BASE_URL}/api/health`)
  return response.json()
}
