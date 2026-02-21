"use client"

import { useState } from "react"
import { runV2Analysis, V2AnalysisResult, TimeFrame } from "@/lib/api"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import TimeframeAnalysis from "@/components/TimeframeAnalysis"

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

  const renderQuickAnalysis = () => {
    if (!result) return null

    return (
      <>
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
              {result.section_reasoning && result.section_reasoning[section] && (
                <p className="text-xs text-gray-500 mt-2">{result.section_reasoning[section]}</p>
              )}
            </div>
          ))}
        </div>

        {/* Headline Analysis */}
        {result.headlines_fetched > 0 && (
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
            <h2 className="text-xl font-semibold mb-4">📰 Headline Context</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-blue-400">{result.headlines_fetched}</div>
                <div className="text-sm text-gray-500">Headlines Fetched</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-purple-400">{result.headline_adjustment > 0 ? '+' : ''}{result.headline_adjustment}</div>
                <div className="text-sm text-gray-500">Score Adjustment</div>
              </div>
            </div>
            {result.headline_reasoning && (
              <p className="text-sm text-gray-400">{result.headline_reasoning}</p>
            )}
          </div>
        )}

        {/* Data Freshness */}
        {result.data_freshness_info && (
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
            <h2 className="text-xl font-semibold mb-4">🕐 Data Freshness</h2>
            <div className="text-sm text-gray-400">
              {result.data_freshness_info.warnings?.length > 0 && (
                <div className="mb-2">
                  <strong className="text-yellow-400">Warnings:</strong>
                  <ul className="list-disc list-inside mt-1">
                    {result.data_freshness_info.warnings.map((w: string, i: number) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </>
    )
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

        <Tabs defaultValue="quick-analysis" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="quick-analysis">Quick Analysis</TabsTrigger>
            <TabsTrigger value="timeframe-analysis">Timeframe Analysis</TabsTrigger>
          </TabsList>
          
          <TabsContent value="quick-analysis" className="space-y-6">
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
              <div className="space-y-6">{renderQuickAnalysis()}</div>
            )}
            
            {!result && !loading && (
              <div className="bg-gray-800 rounded-xl p-8 border border-gray-700 text-center">
                <div className="text-gray-400 mb-4">
                  Click "Run Analysis" to get the latest Bitcoin macro assessment
                </div>
              </div>
            )}
          </TabsContent>
          
          <TabsContent value="timeframe-analysis">
            <TimeframeAnalysis />
          </TabsContent>
        </Tabs>
      </div>
    </main>
  )
}
