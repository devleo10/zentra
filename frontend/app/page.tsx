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
            {/* Verdict */}
            <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-5xl font-bold">{result.final_score}</div>
                  <div className="text-gray-500 text-xs mt-1">Score / 100</div>
                </div>
                <div className="text-right space-y-1.5">
                  <div className={`inline-block px-3 py-1 rounded-full text-sm font-semibold ${getBiasStyle(result.bias)}`}>
                    {result.bias}
                  </div>
                  <div className="text-gray-300 text-sm">{result.action}</div>
                  <div className="text-gray-500 text-xs">{result.confidence_pct.toFixed(0)}% confidence</div>
                </div>
              </div>
              {result.btc_price && (
                <div className="mt-3 pt-3 border-t border-gray-800 text-sm text-gray-400">
                  BTC <span className="text-white font-mono font-semibold">${result.btc_price.toLocaleString()}</span>
                </div>
              )}
            </div>

            {/* Analyst Commentary */}
            {result.narrative && (
              <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800 space-y-3">
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Analyst Commentary</div>
                <p className="text-sm text-gray-200 leading-relaxed">{result.narrative}</p>
                {(result.key_risk || result.catalyst_to_watch) && (
                  <div className="grid grid-cols-1 gap-2 pt-2 border-t border-gray-800">
                    {result.key_risk && (
                      <div className="flex gap-2 text-sm">
                        <span className="text-red-400 font-semibold shrink-0">Risk:</span>
                        <span className="text-gray-300">{result.key_risk}</span>
                      </div>
                    )}
                    {result.catalyst_to_watch && (
                      <div className="flex gap-2 text-sm">
                        <span className="text-blue-400 font-semibold shrink-0">Watch:</span>
                        <span className="text-gray-300">{result.catalyst_to_watch}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Section Scores */}
            <div className="bg-gray-900 rounded-2xl p-5 border border-gray-800 space-y-3">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Breakdown</div>
              {Object.entries(result.section_scores).map(([key, score]) => (
                <div key={key}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-300">{SECTION_LABELS[key] ?? key}</span>
                    <span className={`font-semibold ${scoreColor(score)}`}>{score}</span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-1.5">
                    <div className={`h-1.5 rounded-full ${barColor(score)}`} style={{ width: `${score}%` }} />
                  </div>
                </div>
              ))}
            </div>

            {/* Key Data */}
            <div className="grid grid-cols-2 gap-3">
              {/* CPI */}
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
                <div className="text-xs text-gray-500 mb-1">CPI Inflation</div>
                <div className="text-xl font-bold text-white">
                  {result.cpi_yoy_rate != null
                    ? `${result.cpi_yoy_rate.toFixed(1)}%`
                    : result.cpi_mom_change != null
                    ? `${result.cpi_mom_change > 0 ? "+" : ""}${result.cpi_mom_change.toFixed(2)}% MoM`
                    : "—"}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {result.cpi_core_yoy_rate != null
                    ? `Core ${result.cpi_core_yoy_rate.toFixed(1)}%`
                    : result.cpi_yoy_rate != null && result.cpi_mom_change != null
                    ? `MoM ${result.cpi_mom_change > 0 ? "+" : ""}${result.cpi_mom_change.toFixed(2)}%`
                    : "Year-over-year"}
                </div>
              </div>

              {/* DXY */}
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
                <div className="text-xs text-gray-500 mb-1">DXY</div>
                <div className="text-xl font-bold text-white">
                  {result.dxy_value != null ? result.dxy_value.toFixed(2) : "—"}
                </div>
                <div className={`text-xs mt-0.5 ${
                  result.dxy_change_7d != null
                    ? result.dxy_change_7d < 0 ? "text-green-400" : result.dxy_change_7d > 0 ? "text-red-400" : "text-gray-500"
                    : "text-gray-500"
                }`}>
                  {result.dxy_change_7d != null
                    ? `7D ${result.dxy_change_7d > 0 ? "+" : ""}${result.dxy_change_7d.toFixed(2)}%`
                    : "US Dollar Index"}
                </div>
              </div>

              {/* Oil */}
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
                <div className="text-xs text-gray-500 mb-1">WTI Oil</div>
                <div className="text-xl font-bold text-white">
                  {result.oil_price != null ? `$${result.oil_price.toFixed(0)}` : "—"}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">USD / barrel</div>
              </div>

              {/* VIX */}
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
                <div className="text-xs text-gray-500 mb-1">VIX</div>
                <div className={`text-xl font-bold ${
                  result.vix != null
                    ? result.vix > 20 ? "text-red-400" : result.vix < 15 ? "text-green-400" : "text-white"
                    : "text-white"
                }`}>
                  {result.vix != null ? result.vix.toFixed(1) : "—"}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {result.ten_year_yield != null ? `10Y ${result.ten_year_yield.toFixed(2)}%` : "Volatility index"}
                </div>
              </div>
            </div>

            {/* Score adjustments */}
            {(result.headline_adjustment !== 0 || result.cross_signal_adjustment !== 0) && (
              <div className="bg-gray-900 rounded-xl p-4 border border-gray-800 space-y-2 text-sm">
                {result.headline_adjustment !== 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">News adjustment</span>
                    <span className={`font-semibold ${result.headline_adjustment > 0 ? "text-green-400" : "text-red-400"}`}>
                      {result.headline_adjustment > 0 ? "+" : ""}{result.headline_adjustment} pts
                    </span>
                  </div>
                )}
                {result.cross_signal_adjustment !== 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Cross-signal adjustment</span>
                    <span className={`font-semibold ${result.cross_signal_adjustment > 0 ? "text-green-400" : "text-red-400"}`}>
                      {result.cross_signal_adjustment > 0 ? "+" : ""}{result.cross_signal_adjustment} pts
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Timestamp */}
            <div className="text-center text-xs text-gray-600">
              {new Date(result.timestamp).toLocaleString()}
            </div>
          </>
        )}
      </div>
    </main>
  )
}
