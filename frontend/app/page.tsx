"use client"

import { useState } from "react"
import { runAnalysis, VerdictResponse } from "@/lib/api"
import { ScoreCard } from "@/components/ScoreCard"
import { ScoreGauge } from "@/components/ScoreGauge"
import { VerdictPanel } from "@/components/VerdictPanel"

export default function Home() {
  const [verdict, setVerdict] = useState<VerdictResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleAnalyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await runAnalysis()
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

        <div className="mb-6">
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-semibold py-3 px-6 rounded-lg shadow-md transition-colors"
          >
            {loading ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>

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
              Click "Run Analysis" to generate a Bitcoin macro analysis report
            </p>
          </div>
        )}
      </div>
    </main>
  )
}


