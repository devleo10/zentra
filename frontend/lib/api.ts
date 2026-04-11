/**
 * API client for backend — v2 (Deterministic Engine) + Legacy v1
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"

export type TimeFrame = "current" | "week" | "month"

export class ApiError extends Error {
  status: number
  retryAfterSeconds?: number

  constructor(message: string, status: number, retryAfterSeconds?: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.retryAfterSeconds = retryAfterSeconds
  }
}

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

export interface V2ReleaseCalendarEntry {
  next_release_date: string | null
  latest_known_date?: string | null
  source?: string | null
  method?: string | null
}

export interface V2AnalysisResult {
  timestamp: string
  btc_price: number | null
  /** Window % change aligned with selected analysis timeframe */
  btc_change?: number | null
  btc_change_24h?: number | null
  btc_change_7d?: number | null
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
  regime?: string | null
  regime_reasoning?: string | null
  confidence_breakdown?: Record<string, number> | null
  data_quality_score?: number | null
  sanity_flags?: string[] | null
  contradiction_flags?: string[] | null
  section_confidence_multipliers?: Record<string, number> | null
  section_weight_multipliers?: Record<string, number> | null
  config_hash: string
  prompt_version: string
  llm_model: string
  fed_tone?: "hawkish" | "dovish" | "neutral"
  fed_tone_score?: number | null
  fed_tone_summary?: string | null
  fed_tone_confidence_pct?: number | null
  fed_tone_key_signals?: Array<{ text: string; type: string; reason: string }> | null
  dovish_keyword_count: number
  hawkish_keyword_count: number
  pivot_keyword_count: number
  cpi_mom_change: number | null
  cpi_latest_date?: string | null
  cpi_yoy_rate: number | null
  core_cpi_latest_date?: string | null
  cpi_core_mom_change: number | null
  cpi_core_yoy_rate: number | null
  cpi_trend: string | null
  cpi_mom_avg_3m: number | null
  cpi_mom_avg_3m_prior: number | null
  cpi_mom_avg_3m_trend: string | null
  core_cpi_mom_avg_3m: number | null
  core_cpi_mom_avg_3m_prior: number | null
  core_cpi_mom_avg_3m_trend: string | null
  pce_mom_change: number | null
  pce_mom_avg_3m: number | null
  pce_mom_avg_3m_prior: number | null
  pce_mom_avg_3m_trend: string | null
  dxy_value: number | null
  dxy_change?: number | null
  dxy_change_7d: number | null
  dxy_change_label?: string | null
  dxy_change_unit?: "percent" | "points" | null
  /** Rolling ~1 calendar month % (TradingView-style), when provided by the fetcher */
  dxy_change_rolling_1m?: number | null
  dxy_change_rolling_1m_label?: string | null
  dxy_comparison_date_rolling_1m?: string | null
  dxy_trend: string | null
  /** Yahoo symbol, EURUSD proxy, FRED_DTWEXBGS, last_snapshot, etc. */
  dxy_source?: string | null
  dxy_observed_at?: string | null
  dxy_fetched_at?: string | null
  vix: number | null
  vix_observed_at?: string | null
  vix_fetched_at?: string | null
  ten_year_yield: number | null
  ten_year_yield_trend: string | null
  oil_price: number | null
  oil_observed_at?: string | null
  oil_fetched_at?: string | null
  oil_change: number | null
  oil_change_label?: string | null
  oil_change_unit?: "percent" | "points" | null
  oil_trend: string | null
  oil_source?: string | null
  cross_signal_adjustment: number
  cross_signal_reasoning: string
  narrative: string
  key_risk: string
  catalyst_to_watch: string
  // Economy indicators
  unemployment_rate: number | null
  jobs_latest_date?: string | null
  unemployment_trend: string | null
  unemployment_trend_mom: string | null
  unemployment_trend_3m: string | null
  unemployment_3m_avg: number | null
  unemployment_history_3: Array<{ date: string; rate: number }> | null
  nfp_change: number | null
  cpi_value?: number | null
  cpi_value_avg_3m?: number | null
  cpi_value_avg_3m_prior?: number | null
  core_cpi_value?: number | null
  core_cpi_value_avg_3m?: number | null
  core_cpi_value_avg_3m_prior?: number | null
  gdp_growth_rate: number | null
  gdp_trend: string | null
  gdp_latest_date?: string | null
  pce_value?: number | null
  pce_value_avg_3m?: number | null
  pce_value_avg_3m_prior?: number | null
  pce_latest_date?: string | null
  pmi_value: number | null
  pmi_previous_value?: number | null
  pmi_delta_value?: number | null
  pmi_latest_date?: string | null
  pmi_status: string | null
  pmi_trend: string | null
  pmi_source?: string | null
  pmi_proxy_note?: string | null
  m2_trend: string | null
  m2_latest_date?: string | null
  m2_change: number | null
  m2_yoy_change: number | null
  release_calendar?: Record<string, V2ReleaseCalendarEntry>
  // Gold & VIX trends
  sp500_price: number | null
  sp500_change: number | null
  sp500_change_label?: string | null
  sp500_change_unit?: "percent" | "points" | null
  sp500_trend: string | null
  sp500_source?: string | null
  sp500_observed_at?: string | null
  sp500_fetched_at?: string | null
  gold_price: number | null
  gold_observed_at?: string | null
  gold_fetched_at?: string | null
  gold_change: number | null
  gold_change_label?: string | null
  gold_change_unit?: "percent" | "points" | null
  gold_trend: string | null
  gold_source?: string | null
  vix_change: number | null
  vix_change_label?: string | null
  vix_change_unit?: "percent" | "points" | null
  vix_trend: string | null
  vix_source?: string | null
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
  fed_balance_sheet_trend?: string | null
  // Natural gas
  natgas_price: number | null
  natgas_change: number | null
  natgas_change_label?: string | null
  natgas_change_unit?: "percent" | "points" | null
  natgas_trend: string | null
  natgas_source?: string | null
  move_index_value: number | null
  move_index_change: number | null
  move_index_change_label?: string | null
  move_index_change_unit?: "percent" | "points" | null
  move_index_trend: string | null
  eem_price?: number | null
  eem_change?: number | null
  eem_change_label?: string | null
  eem_change_unit?: "percent" | "points" | null
  eem_trend?: string | null
  eem_source?: string | null
  // BTC market structure
  btc_dominance: number | null
  stablecoin_dominance: number | null
  btc_dominance_change?: number | null
  stablecoin_dominance_change?: number | null
  btc_dominance_source?: string | null
  stablecoin_dominance_source?: string | null
  btc_dominance_change_source?: string | null
  stablecoin_dominance_change_source?: string | null
  btc_ma200: number | null
  btc_realized_vol_30d: number | null
  btc_observed_at?: string | null
  btc_fetched_at?: string | null
  btc_etf_volume: number | null
  btc_etf_net_flow_musd?: number | null
  btc_etf_flow_date?: string | null
  btc_etf_source?: string | null
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

export interface V2AnalysisMeta {
  cacheStatus: string | null
  cacheAgeSeconds: number | null
  refreshInProgress: boolean
}

export interface V2AnalysisResponse {
  data: V2AnalysisResult
  meta: V2AnalysisMeta
}

export interface V2AnalysisProgress {
  phase: "starting" | "polling" | "retrying"
  message: string
  nextRetryInSeconds: number
  elapsedSeconds: number
  maxWaitSeconds: number
}

// ── v2 API Calls ─────────────────────────────────────────────────────────

async function _fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

function _parseApiError(response: Response, body: any): ApiError {
  let detail = ""
  let retryAfterSeconds: number | undefined
  try {
    if (body?.detail) {
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)
    } else if (body?.message) {
      detail = String(body.message)
      if (Array.isArray(body?.critical_failures) && body.critical_failures.length > 0) {
        detail += ` Critical: ${body.critical_failures.join(" | ")}`
      }
      if (Array.isArray(body?.warnings) && body.warnings.length > 0) {
        detail += ` Warnings: ${body.warnings.join(" | ")}`
      }
    } else {
      detail = JSON.stringify(body)
    }
    if (body?.retry_after_seconds != null) {
      const parsed = Number(body.retry_after_seconds)
      if (Number.isFinite(parsed) && parsed > 0) retryAfterSeconds = parsed
    }
  } catch { /* ignore */ }

  if (!retryAfterSeconds) {
    const ra = response.headers.get("Retry-After")
    if (ra) {
      const parsed = Number(ra)
      if (Number.isFinite(parsed) && parsed > 0) retryAfterSeconds = parsed
    }
  }
  return new ApiError(
    `v2 Analysis failed: ${response.status} ${response.statusText}${detail ? ` — ${detail}` : ""}`,
    response.status,
    retryAfterSeconds
  )
}

const _FETCH_TIMEOUT_MS = 180_000
const _ANALYSIS_POLL_MAX_WAIT_MS = 300_000
const _ANALYSIS_POLL_MIN_DELAY_MS = 2_000
const _ANALYSIS_POLL_MAX_DELAY_MS = 12_000

function _sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function _retryDelayMs(response: Response, body: any): number {
  const fromHeader = Number(response.headers.get("Retry-After"))
  const fromBody = Number(body?.retry_after_seconds)
  const seconds =
    (Number.isFinite(fromBody) && fromBody > 0 ? fromBody : NaN)
      || (Number.isFinite(fromHeader) && fromHeader > 0 ? fromHeader : NaN)
      || 4
  const ms = seconds * 1_000
  return Math.max(_ANALYSIS_POLL_MIN_DELAY_MS, Math.min(_ANALYSIS_POLL_MAX_DELAY_MS, ms))
}

function _readAnalysisMeta(response: Response): V2AnalysisMeta {
  const cacheStatus = response.headers.get("X-Analysis-Cache")
  const cacheAgeRaw = response.headers.get("X-Cache-Age-Seconds")
  const refreshStatus = response.headers.get("X-Refresh-Status")
  const cacheAgeParsed = cacheAgeRaw != null ? Number(cacheAgeRaw) : NaN
  return {
    cacheStatus,
    cacheAgeSeconds: Number.isFinite(cacheAgeParsed) ? cacheAgeParsed : null,
    refreshInProgress:
      refreshStatus === "in_progress" ||
      cacheStatus === "SNAPSHOT_STALE_REFRESH_STARTED",
  }
}

function _isV2AnalysisResult(data: any): data is V2AnalysisResult {
  return (
    !!data
    && typeof data === "object"
    && typeof data.final_score === "number"
    && typeof data.bias === "string"
    && typeof data.action === "string"
    && !!data.section_scores
    && typeof data.section_scores === "object"
  )
}

export async function runV2Analysis(
  timeframe: TimeFrame = "current",
  onProgress?: (progress: V2AnalysisProgress) => void,
): Promise<V2AnalysisResponse> {
  const pollUrl = `${API_BASE_URL}/api/v2/analyze/${timeframe}`
  const kickoffUrl = `${pollUrl}?fresh=true`
  const startedAt = Date.now()
  const maxWaitSeconds = Math.floor(_ANALYSIS_POLL_MAX_WAIT_MS / 1000)

  const emitProgress = (phase: V2AnalysisProgress["phase"], message: string, waitMs: number) => {
    if (!onProgress) return
    onProgress({
      phase,
      message,
      nextRetryInSeconds: Math.max(1, Math.ceil(waitMs / 1000)),
      elapsedSeconds: Math.max(0, Math.floor((Date.now() - startedAt) / 1000)),
      maxWaitSeconds,
    })
  }

  // Kick off a fresh run first.
  // This endpoint now returns 202 while work is in progress.
  try {
    const kickoff = await _fetchWithTimeout(kickoffUrl, _FETCH_TIMEOUT_MS)
    if (kickoff.status === 429) {
      let body: any = null
      try { body = await kickoff.json() } catch { /* ignore */ }
      const waitMs = _retryDelayMs(kickoff, body)
      emitProgress(
        "retrying",
        "Server is busy due to rate limits. Retrying automatically.",
        waitMs,
      )
      await _sleep(waitMs)
    }
    if (kickoff.ok && kickoff.status !== 202) {
      const data = await kickoff.json()
      if (data?.status !== "in_progress") {
        if (!_isV2AnalysisResult(data)) {
          throw new Error("Backend returned an unexpected analysis payload format.")
        }
        return { data, meta: _readAnalysisMeta(kickoff) }
      }
    }
    emitProgress("starting", "Analysis started on backend.", 4_000)
  } catch {
    // Backend may still be waking up; polling loop below handles recovery.
    emitProgress("retrying", "Backend waking up... retrying shortly.", 5_000)
  }

  while (Date.now() - startedAt < _ANALYSIS_POLL_MAX_WAIT_MS) {
    let response: Response
    try {
      response = await _fetchWithTimeout(pollUrl, _FETCH_TIMEOUT_MS)
    } catch (err: any) {
      // Network / timeout / abort — backend may still be running (cold start / in-progress).
      emitProgress("retrying", "Waiting for backend response...", 5_000)
      await _sleep(5_000)
      continue
    }

    if (response.status === 202) {
      let body: any = null
      try { body = await response.json() } catch { /* ignore */ }
      const waitMs = _retryDelayMs(response, body)
      emitProgress("polling", body?.message || "Analysis is still running on backend.", waitMs)
      await _sleep(waitMs)
      continue
    }

    if (response.status === 429) {
      let body: any = null
      try { body = await response.json() } catch { /* ignore */ }
      const waitMs = _retryDelayMs(response, body)
      const bodyMessage = typeof body?.message === "string" ? body.message : ""
      const message = body?.error === "analysis_already_running"
        ? (bodyMessage || "Analysis is already running. Waiting for completion.")
        : (bodyMessage || "Server is busy due to rate limits. Retrying automatically.")
      emitProgress("retrying", message, waitMs)
      await _sleep(waitMs)
      continue
    }

    if (!response.ok) {
      let body: any
      try { body = await response.json() } catch { body = await response.text() }
      throw _parseApiError(response, body)
    }

    const data = await response.json()
    // Defensive guard: if backend unexpectedly returns an in-progress payload with 200.
    if (data?.status === "in_progress") {
      const waitMs = _retryDelayMs(response, data)
      emitProgress("polling", data?.message || "Analysis in progress.", waitMs)
      await _sleep(waitMs)
      continue
    }
    if (!_isV2AnalysisResult(data)) {
      throw new Error("Backend returned an unexpected analysis payload format.")
    }
    return { data, meta: _readAnalysisMeta(response) }
  }

  throw new Error("Analysis is still running. Please retry in a few seconds.")
}

export async function pingKeepAlive(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/api/keepalive`, { method: "GET", cache: "no-store" })
  } catch {
    // no-op: keepalive should never break UI flow
  }
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

// ── Dashboard auth helpers ──────────────────────────────────────────────────
export interface AuthStatusResponse {
  auth_required: boolean
}

export interface LoginResponse {
  access_token: string | null
  token_type: string
  expires_in: number
  auth_required: boolean
}

export async function getAuthStatus(): Promise<AuthStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/status`, { cache: "no-store" })
  if (!response.ok) throw new Error(`Auth status fetch failed: ${response.statusText}`)
  return response.json()
}

export async function loginDashboard(clientId: string, clientSecret: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Login failed: ${res.status} ${res.statusText} - ${text}`)
  }
  return res.json()
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
