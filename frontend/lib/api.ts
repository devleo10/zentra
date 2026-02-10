/**
 * API client for backend
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export interface SectionScore {
  name: string
  score: number
  signals: string[]
  reasoning: string
  data_used?: Record<string, any>
}

export interface VerdictResponse {
  timestamp: string
  sections: SectionScore[]
  final_score: number
  bias: string
  action: string
  confidence: string
  summary: string
}

export async function runAnalysis(): Promise<VerdictResponse> {
  // Run real analysis - no fallback to demo
  const response = await fetch(`${API_BASE_URL}/api/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
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

export async function analyzeSection(section: string): Promise<SectionScore> {
  const response = await fetch(`${API_BASE_URL}/api/analyze/${section}`, {
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


