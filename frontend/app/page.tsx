"use client"

import { useState } from "react"
import { runV2Analysis, V2AnalysisResult, TimeFrame } from "@/lib/api"

const TIMEFRAMES: { value: TimeFrame; label: string }[] = [
  { value: "current", label: "Now" },
  { value: "week",    label: "7D" },
  { value: "month",   label: "30D" },
  { value: "year",    label: "1Y" },
]

const SECTION_LABELS: Record<string, string> = {
  inflation:      "Inflation",
  fed_policy:     "Fed Policy",
  liquidity:      "Liquidity",
  dxy:            "US Dollar",
  risk_sentiment: "Risk",
}

const getBiasStyle = (bias: string) => {
  const b = bias.toLowerCase()
  if (b.includes("strong bull")) return "bg-green-500 text-white"
  if (b.includes("bull"))        return "bg-green-400 text-white"
  if (b.includes("bear") || b.includes("high risk")) return "bg-red-500 text-white"
  return "bg-yellow-400 text-gray-900"
}

const scoreColor = (s: number) =>
  s >= 65 ? "text-green-400" : s >= 40 ? "text-yellow-400" : "text-red-400"

const barColor = (s: number) =>
  s >= 65 ? "bg-green-500" : s >= 40 ? "bg-yellow-500" : "bg-red-500"

export default function Home() {
  const [timeframe, setTimeframe] = useState<TimeFrame>("current")
  const [results, setResults] = useState<Partial<Record<TimeFrame, V2AnalysisResult>>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const result = results[timeframe] ?? null

  const handleAnalyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await runV2Analysis()
      setResults(prev => ({ ...prev, [timeframe]: data }))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center px-4 py-10">
      <div className="w-full max-w-xl space-y-5">

        {/* Header */}
        <div className="text-center">
          <h1 className="text-2xl font-bold tracking-tight">BTC Macro Signal</h1>
          <p className="text-gray-500 text-sm mt-1">Real-time macro analysis for Bitcoin</p>
        </div>

        {/* Timeframe + Run */}
        <div className="flex gap-2">
          <div className="flex bg-gray-900 rounded-xl border border-gray-800 p-1 gap-1">
            {TIMEFRAMES.map(tf => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  timeframe === tf.value
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                {tf.label}
              </button>
            ))}
          </div>
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="flex-1 py-2 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-400 transition-colors"
          >
            {loading ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-900/40 border border-red-700 text-red-300 text-sm px-4 py-3 rounded-lg">
            {error}
          </div>
        )}

        {/* Empty state */}
        {!result && !loading && (
          <div className="text-center text-gray-600 text-sm py-10">
            Select a timeframe and press Run Analysis
          </div>
        )}

        {result && (
          <>
            {/* Verdict — score, bias, action, BTC */}
            <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-baseline gap-3">
                  <span className="text-4xl font-bold tabular-nums">{result.final_score}</span>
                  <span className="text-gray-500 text-sm">/ 100</span>
                  {(result.headline_adjustment !== 0 || result.cross_signal_adjustment !== 0) && (
                    <span className="text-gray-500 text-xs">
                      {result.weighted_numeric_score}
                      {result.headline_adjustment !== 0 && (
                        <span className={result.headline_adjustment > 0 ? "text-green-400" : "text-red-400"}>
                          {" + "}{result.headline_adjustment}
                        </span>
                      )}
                      {result.cross_signal_adjustment !== 0 && (
                        <span className={result.cross_signal_adjustment > 0 ? "text-green-400" : "text-red-400"}>
                          {" + "}{result.cross_signal_adjustment}
                        </span>
                      )}
                      {" = "}{result.final_score}
                    </span>
                  )}
                </div>
                <div className="text-right">
                  <div className={`inline-block px-3 py-1 rounded-full text-sm font-semibold ${getBiasStyle(result.bias)}`}>
                    {result.bias}
                  </div>
                  <p className="text-gray-300 text-sm mt-1">{result.action}</p>
                  <p className="text-gray-500 text-xs mt-0.5">{result.confidence_pct.toFixed(0)}% confidence</p>
                </div>
              </div>
              {result.btc_price != null && (
                <div className="mt-3 pt-3 border-t border-gray-800 text-sm text-gray-400">
                  BTC <span className="text-white font-mono font-semibold">${result.btc_price.toLocaleString()}</span>
                </div>
              )}
            </div>

            {/* Commentary — narrative only when it looks like prose (not the raw formula) */}
            {result.narrative && !result.narrative.startsWith("Numeric:") && (
              <div className="bg-gray-900 rounded-2xl p-4 border border-gray-800">
                <p className="text-sm text-gray-200 leading-relaxed">{result.narrative}</p>
                {(result.key_risk || result.catalyst_to_watch) && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 pt-2 border-t border-gray-800 text-xs">
                    {result.key_risk && (
                      <span><span className="text-red-400 font-medium">Risk:</span> <span className="text-gray-400">{result.key_risk}</span></span>
                    )}
                    {result.catalyst_to_watch && (
                      <span><span className="text-blue-400 font-medium">Watch:</span> <span className="text-gray-400">{result.catalyst_to_watch}</span></span>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Section breakdown */}
            <div className="bg-gray-900 rounded-2xl p-4 border border-gray-800">
              <div className="flex justify-between text-xs text-gray-500 mb-2">Breakdown</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
                {Object.entries(result.section_scores).map(([key, score]) => (
                  <div key={key} className="flex items-center gap-2">
                    <span className="text-gray-400 text-sm w-24 shrink-0">{SECTION_LABELS[key] ?? key}</span>
                    <div className="flex-1 min-w-0 bg-gray-800 rounded-full h-2">
                      <div className={`h-2 rounded-full ${barColor(score)}`} style={{ width: `${score}%` }} />
                    </div>
                    <span className={`text-sm font-semibold w-6 text-right ${scoreColor(score)}`}>{score}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Key metrics — single row */}
            <div className="flex flex-wrap gap-2 text-sm">
              {result.cpi_yoy_rate != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  CPI <span className="text-white font-medium">{result.cpi_yoy_rate.toFixed(1)}%</span>
                  {result.cpi_core_yoy_rate != null && <span className="text-gray-500"> · Core {result.cpi_core_yoy_rate.toFixed(1)}%</span>}
                </span>
              )}
              {result.dxy_value != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  DXY <span className="text-white font-medium">{result.dxy_value.toFixed(2)}</span>
                  {result.dxy_change_7d != null && (
                    <span className={result.dxy_change_7d >= 0 ? "text-red-400" : "text-green-400"}>
                      {" "}{result.dxy_change_7d >= 0 ? "+" : ""}{result.dxy_change_7d.toFixed(2)}% 7D
                    </span>
                  )}
                </span>
              )}
              {result.oil_price != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  WTI <span className="text-white font-medium">${result.oil_price.toFixed(0)}</span>
                </span>
              )}
              {result.vix != null && (
                <span className={`bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 ${
                  result.vix > 20 ? "text-red-400" : result.vix < 15 ? "text-green-400" : "text-gray-300"
                }`}>
                  VIX <span className="font-medium">{result.vix.toFixed(1)}</span>
                </span>
              )}
              {result.ten_year_yield != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  10Y <span className="text-white font-medium">{result.ten_year_yield.toFixed(2)}%</span>
                </span>
              )}
            </div>

            <p className="text-center text-xs text-gray-600">{new Date(result.timestamp).toLocaleString()}</p>
          </>
        )}
      </div>
    </main>
  )
}
