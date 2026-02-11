"use client"

import { useState } from "react"
import { runAnalysis, VerdictResponse, TimeFrame } from "@/lib/api"
import { ScoreCard } from "@/components/ScoreCard"
import { ScoreGauge } from "@/components/ScoreGauge"
import { VerdictPanel } from "@/components/VerdictPanel"

const TIMEFRAME_OPTIONS: { value: TimeFrame; label: string; description: string }[] = [
  { value: "current", label: "Current", description: "Real-time latest data" },
  { value: "week", label: "Week", description: "7-day analysis" },
  { value: "month", label: "Month", description: "30-day analysis" },
  { value: "year", label: "Year", description: "365-day analysis" },
]

export default function Home() {
  const [verdict, setVerdict] = useState<VerdictResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedTimeframe, setSelectedTimeframe] = useState<TimeFrame>("current")

  const handleAnalyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await runAnalysis(selectedTimeframe)
      setVerdict(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto">
        <header className="mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            BTC Macro AI Agent Dashboard
          </h1>
          <p className="text-gray-600">
            AI-powered Bitcoin macro analysis using money rotation and Fed policy frameworks
          </p>
        </header>

        <div className="mb-6 flex flex-wrap items-center gap-4">
          {/* Timeframe Selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Timeframe:</label>
            <div className="flex rounded-lg border border-gray-300 overflow-hidden">
              {TIMEFRAME_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setSelectedTimeframe(option.value)}
                  className={`px-4 py-2 text-sm font-medium transition-colors ${
                    selectedTimeframe === option.value
                      ? "bg-blue-600 text-white"
                      : "bg-white text-gray-700 hover:bg-gray-100"
                  }`}
                  title={option.description}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-semibold py-3 px-6 rounded-lg shadow-md transition-colors"
          >
            {loading ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>

        {/* Current timeframe indicator */}
        {verdict && (
          <div className="mb-4 inline-flex items-center gap-2 bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm">
            <span className="font-medium">Analysis Timeframe:</span>
            <span className="capitalize">{verdict.timeframe || selectedTimeframe}</span>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-6">
            Error: {error}
          </div>
        )}

        {verdict && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
              {verdict.sections.map((section, idx) => (
                <ScoreCard key={idx} section={section} />
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
              <div className="bg-white rounded-lg shadow-md p-6 flex justify-center">
                <ScoreGauge score={verdict.final_score} />
              </div>
              <VerdictPanel verdict={verdict} />
            </div>
          </>
        )}

        {!verdict && !loading && (
          <div className="bg-white rounded-lg shadow-md p-12 text-center">
            <p className="text-gray-500 text-lg">
              Select a timeframe and click "Run Analysis" to generate a Bitcoin macro analysis report
            </p>
          </div>
        )}
      </div>
    </main>
  )
}


