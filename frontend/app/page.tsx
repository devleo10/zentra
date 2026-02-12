"use client"

import { useState } from "react"
import { runV2Analysis, V2AnalysisResult, TimeFrame } from "@/lib/api"

const TIMEFRAME_OPTIONS: { value: TimeFrame; label: string; description: string }[] = [
  { value: "current", label: "Current", description: "Real-time latest data" },
  { value: "week", label: "Week", description: "7-day analysis" },
  { value: "month", label: "Month", description: "30-day analysis" },
  { value: "year", label: "Year", description: "365-day analysis" },
]

// Helper to get score color
const getScoreColor = (score: number) => {
  if (score >= 70) return "text-green-600 bg-green-50 border-green-200"
  if (score >= 50) return "text-yellow-600 bg-yellow-50 border-yellow-200"
  return "text-red-600 bg-red-50 border-red-200"
}

const getBiasColor = (bias: string) => {
  const lowerBias = bias.toLowerCase()
  if (lowerBias.includes("bull")) return "text-green-700 bg-green-100"
  if (lowerBias.includes("bear") || lowerBias.includes("risk")) return "text-red-700 bg-red-100"
  return "text-yellow-700 bg-yellow-100"
}

export default function Home() {
  const [result, setResult] = useState<V2AnalysisResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedTimeframe, setSelectedTimeframe] = useState<TimeFrame>("current")

  const handleAnalyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const analysisResult = await runV2Analysis()
      setResult(analysisResult)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-900 text-white p-8">
      <div className="max-w-7xl mx-auto">
        <header className="mb-8">
          <h1 className="text-4xl font-bold mb-2">
            🪙 BTC Macro AI Agent Dashboard
          </h1>
          <p className="text-gray-400">
            Deterministic Bitcoin macro analysis — numeric scoring, headline context, full audit trail
          </p>
        </header>

        <div className="mb-6 flex flex-wrap items-center gap-4">
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white font-semibold py-3 px-6 rounded-lg shadow-md transition-colors"
          >
            {loading ? "⏳ Analyzing..." : "🚀 Run Analysis"}
          </button>
          <span className="text-gray-500 text-sm">
            (Deterministic v2 engine — no black-box LLM scoring)
          </span>
        </div>

        {error && (
          <div className="bg-red-900/50 border border-red-500 text-red-200 px-4 py-3 rounded mb-6">
            ❌ Error: {error}
          </div>
        )}

        {result && (
          <div className="space-y-6">
            {/* Main Score Card */}
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div>
                  <div className="text-6xl font-bold mb-2">{result.final_score}</div>
                  <div className="text-gray-400">Final Score (0-100)</div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <span className={`px-4 py-2 rounded-full font-semibold ${getBiasColor(result.bias)}`}>
                    {result.bias}
                  </span>
                  <span className="text-gray-300">{result.action}</span>
                  <span className="text-sm text-gray-500">
                    Confidence: {result.confidence_pct.toFixed(0)}% ({result.confidence_label})
                  </span>
                </div>
              </div>
              {result.btc_price && (
                <div className="mt-4 text-gray-400">
                  BTC Price: <span className="text-white font-mono">${result.btc_price.toLocaleString()}</span>
                </div>
              )}
            </div>

            {/* Section Scores Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(result.section_scores).map(([section, score]) => (
                <div key={section} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-gray-300 capitalize">{section.replace(/_/g, ' ')}</span>
                    <span className={`text-2xl font-bold ${score >= 60 ? 'text-green-400' : score >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
                      {score}
                    </span>
                  </div>
                  <div className="w-full bg-gray-700 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${score >= 60 ? 'bg-green-500' : score >= 40 ? 'bg-yellow-500' : 'bg-red-500'}`}
                      style={{ width: `${score}%` }}
                    />
                  </div>
                  {result.section_reasoning[section] && (
                    <p className="text-xs text-gray-500 mt-2">{result.section_reasoning[section]}</p>
                  )}
                </div>
              ))}
            </div>

            {/* Headline Analysis */}
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h2 className="text-xl font-semibold mb-4">📰 Headline Context</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-400">{result.headlines_fetched}</div>
                  <div className="text-sm text-gray-500">Headlines Fetched</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-400">{result.dovish_keyword_count}</div>
                  <div className="text-sm text-gray-500">Dovish Keywords</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-red-400">{result.hawkish_keyword_count}</div>
                  <div className="text-sm text-gray-500">Hawkish Keywords</div>
                </div>
                <div className="text-center">
                  <div className={`text-2xl font-bold ${result.headline_adjustment >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {result.headline_adjustment >= 0 ? '+' : ''}{result.headline_adjustment}
                  </div>
                  <div className="text-sm text-gray-500">Score Adjustment</div>
                </div>
              </div>
              <p className="text-gray-400 text-sm">{result.headline_reasoning}</p>
            </div>

            {/* Data Freshness */}
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h2 className="text-xl font-semibold mb-4">📊 Data Freshness</h2>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {result.data_freshness_info.checks.map((check, idx) => (
                  <div key={idx} className={`p-3 rounded-lg border ${
                    check.status === 'FRESH' ? 'border-green-600 bg-green-900/20' :
                    check.status === 'STALE' ? 'border-yellow-600 bg-yellow-900/20' :
                    'border-red-600 bg-red-900/20'
                  }`}>
                    <div className="font-medium text-sm">{check.name}</div>
                    <div className={`text-xs ${
                      check.status === 'FRESH' ? 'text-green-400' :
                      check.status === 'STALE' ? 'text-yellow-400' :
                      'text-red-400'
                    }`}>
                      {check.status}
                    </div>
                  </div>
                ))}
              </div>
              {result.data_freshness_info.warnings.length > 0 && (
                <div className="mt-4 text-yellow-400 text-sm">
                  ⚠️ Warnings: {result.data_freshness_info.warnings.join(', ')}
                </div>
              )}
            </div>

            {/* Audit Info */}
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h2 className="text-xl font-semibold mb-4">🔍 Audit Trail</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <div className="text-gray-500">Timestamp</div>
                  <div className="font-mono">{new Date(result.timestamp).toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-gray-500">Config Hash</div>
                  <div className="font-mono text-xs">{result.config_hash.slice(0, 12)}...</div>
                </div>
                <div>
                  <div className="text-gray-500">Prompt Version</div>
                  <div className="font-mono">{result.prompt_version}</div>
                </div>
                <div>
                  <div className="text-gray-500">LLM Model</div>
                  <div className="font-mono">{result.llm_model}</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {!result && !loading && !error && (
          <div className="bg-gray-800 rounded-xl p-12 text-center border border-gray-700">
            <div className="text-6xl mb-4">📈</div>
            <h2 className="text-2xl font-semibold mb-2">Ready to Analyze</h2>
            <p className="text-gray-400">
              Click &quot;Run Analysis&quot; to fetch macro data and compute the BTC verdict using deterministic scoring.
            </p>
          </div>
        )}
      </div>
    </main>
  )
}
