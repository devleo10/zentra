/**
 * API client for backend
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export type TimeFrame = "current" | "week" | "month" | "year"

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

export async function runAnalysis(timeframe: TimeFrame = "current"): Promise<VerdictResponse> {
  // Run real analysis with timeframe filter
  const response = await fetch(`${API_BASE_URL}/api/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ timeframe }),
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Analysis failed: ${response.statusText} - ${errorText}`)
  }

  return response.json()
}

export async function runDemoAnalysis(): Promise<VerdictResponse> {
  const response = await fetch(`${API_BASE_URL}/api/demo`, {
    method: "GET",
  })

  if (!response.ok) {
    throw new Error(`Demo analysis failed: ${response.statusText}`)
  }

  return response.json()
}

export async function analyzeSection(section: string, timeframe: TimeFrame = "current"): Promise<SectionScore> {
  const response = await fetch(`${API_BASE_URL}/api/analyze/${section}?timeframe=${timeframe}`, {
    method: "GET",
  })

  if (!response.ok) {
    throw new Error(`Section analysis failed: ${response.statusText}`)
  }

  return response.json()
}

export async function healthCheck() {
  const response = await fetch(`${API_BASE_URL}/api/health`)
  return response.json()
}


