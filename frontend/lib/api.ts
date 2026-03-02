/**
 * API client for backend — v2 (Deterministic Engine) + Legacy v1
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export type TimeFrame = "current" | "week" | "month" | "year"

// ── v2 Types (Deterministic Engine) ──────────────────────────────────────

export interface V2SectionScores {
  inflation: number
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
  dovish_keyword_count: number
  hawkish_keyword_count: number
  pivot_keyword_count: number
  cpi_mom_change: number | null
  cpi_yoy_rate: number | null       // YoY inflation rate e.g. 3.1 = "CPI is 3.1%"
  cpi_core_yoy_rate: number | null  // Core CPI YoY (ex food & energy) — from BLS only
  dxy_value: number | null
  dxy_change_7d: number | null
  vix: number | null
  ten_year_yield: number | null
  oil_price: number | null
  cross_signal_adjustment: number
  cross_signal_reasoning: string
  narrative: string
  key_risk: string
  catalyst_to_watch: string
}

export interface V2HistoryEntry extends V2AnalysisResult {
  id: number
}

// ── v2 API Calls ─────────────────────────────────────────────────────────

export async function runV2Analysis(): Promise<V2AnalysisResult> {
  const response = await fetch(`${API_BASE_URL}/api/v2/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })

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
