"use client"

import { useState } from "react"
import { runV2Analysis, V2AnalysisResult, TimeFrame } from "@/lib/api"

const TIMEFRAMES: { value: TimeFrame; label: string }[] = [
  { value: "current", label: "Now" },
  { value: "week",    label: "7D" },
  { value: "month",   label: "30D" },
]

const SECTION_LABELS: Record<string, string> = {
  inflation:      "Inflation",
  economy:        "Economy",
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
      const data = await runV2Analysis(timeframe)
      setResults(prev => ({ ...prev, [timeframe]: data }))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col px-3 py-4 sm:px-6 sm:py-5">
      <div className="w-full max-w-[1600px] mx-auto space-y-3 sm:space-y-4">

        {/* Header + controls — single row */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">BTC Macro Signal</h1>
            <p className="text-gray-500 text-xs sm:text-sm">Real-time macro analysis for Bitcoin</p>
          </div>
          <div className="flex gap-2 items-center">
            <div className="flex bg-gray-900 rounded-xl border border-gray-800 p-1 gap-0.5">
              {TIMEFRAMES.map(tf => (
                <button
                  key={tf.value}
                  onClick={() => setTimeframe(tf.value)}
                  className={`px-2.5 sm:px-3 py-1.5 rounded-lg text-xs sm:text-sm font-medium transition-colors ${
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
              className="py-2 px-4 rounded-xl font-semibold text-xs sm:text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-400 transition-colors whitespace-nowrap"
            >
              {loading ? "Analyzing..." : "Run Analysis"}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-900/40 border border-red-700 text-red-300 text-sm px-4 py-2 rounded-lg">
            {error}
          </div>
        )}

        {/* Empty state */}
        {!result && !loading && (
          <div className="text-center text-gray-600 text-sm py-8">
            Select a timeframe and press Run Analysis
          </div>
        )}

        {result && (
          <>
            {/* Top: Commentary strip (compact) */}
            {result.narrative && !result.narrative.startsWith("Numeric:") && (
              <div className="bg-gray-900 rounded-xl p-3 border border-gray-800">
                <p className="text-xs sm:text-sm text-gray-200 leading-snug line-clamp-2 sm:line-clamp-1">{result.narrative}</p>
                {(result.key_risk || result.catalyst_to_watch) && (
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5 pt-1.5 border-t border-gray-800 text-[11px] sm:text-xs">
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

            {/* Main: two columns on lg — left: Verdict + Breakdown; right: Metrics + Headlines */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.2fr] gap-3 sm:gap-4">
              {/* Left column */}
              <div className="space-y-3 sm:space-y-4">
                {/* Verdict */}
                <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-baseline gap-2">
                      <span className="text-3xl sm:text-4xl font-bold tabular-nums">{result.final_score}</span>
                      <span className="text-gray-500 text-sm">/ 100</span>
                      {(result.headline_adjustment !== 0 || result.cross_signal_adjustment !== 0) && (
                        <span className="text-gray-500 text-[10px] sm:text-xs hidden sm:inline">
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
                      <div className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${getBiasStyle(result.bias)}`}>
                        {result.bias}
                      </div>
                      <p className="text-gray-300 text-xs mt-0.5">{result.action}</p>
                      <p className="text-gray-500 text-[10px] sm:text-xs">
                        {result.confidence_pct.toFixed(0)}% ({result.confidence_label})
                      </p>
                      {result.data_freshness_info?.warnings?.length > 0 && (
                        <p className="text-amber-400 text-[10px]">warnings: {result.data_freshness_info.warnings.length}</p>
                      )}
                    </div>
                  </div>
                  {result.btc_price != null && (
                    <div className="mt-2 pt-2 border-t border-gray-800 text-xs text-gray-400">
                      BTC <span className="text-white font-mono font-semibold">${result.btc_price.toLocaleString()}</span>
                    </div>
                  )}
                </div>

                {/* Breakdown */}
                <div className="bg-gray-900 rounded-xl p-3 border border-gray-800">
                  <div className="text-[10px] sm:text-xs text-gray-500 mb-1.5">Breakdown</div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                    {Object.entries(result.section_scores).map(([key, score]) => (
                      <div key={key} className="flex items-center gap-1.5">
                        <span className="text-gray-400 text-[11px] sm:text-sm w-20 shrink-0">{SECTION_LABELS[key] ?? key}</span>
                        <div className="flex-1 min-w-0 bg-gray-800 rounded-full h-1.5 sm:h-2">
                          <div className={`h-1.5 sm:h-2 rounded-full ${barColor(score)}`} style={{ width: `${score}%` }} />
                        </div>
                        <span className={`text-[11px] sm:text-sm font-semibold w-5 text-right tabular-nums ${scoreColor(score)}`}>{score}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Right column: Key metrics + Headlines */}
              <div className="space-y-3 sm:space-y-4">
                {/* Key metrics — dense grid, more columns when wide */}
                <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-1.5 sm:gap-2 text-xs sm:text-sm">
              {result.cpi_mom_change != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300" title={result.cpi_yoy_rate != null ? `YoY ${result.cpi_yoy_rate.toFixed(1)}%${result.cpi_core_yoy_rate != null ? ` · Core ${result.cpi_core_yoy_rate.toFixed(1)}%` : ""}` : undefined}>
                  CPI MoM <span className="text-white font-medium">{result.cpi_mom_change > 0 ? "+" : ""}{result.cpi_mom_change.toFixed(2)}%</span>
                  <span className={result.cpi_mom_change > 0.05 ? "text-red-400" : result.cpi_mom_change < -0.05 ? "text-green-400" : "text-gray-500"}>
                    {" "}{result.cpi_mom_change > 0.05 ? "▲" : result.cpi_mom_change < -0.05 ? "▼" : "→"}
                  </span>
                </span>
              )}
              {result.dxy_value != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  DXY <span className="text-white font-medium">{result.dxy_value.toFixed(2)}</span>
                  {result.dxy_change_7d != null && (
                    <span className={result.dxy_change_7d > 0.1 ? "text-red-400" : result.dxy_change_7d < -0.1 ? "text-green-400" : "text-gray-500"}>
                      {" "}{result.dxy_change_7d > 0.1 ? "▲" : result.dxy_change_7d < -0.1 ? "▼" : "→"}
                    </span>
                  )}
                </span>
              )}
              {result.oil_price != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  WTI <span className="text-white font-medium">${result.oil_price.toFixed(0)}</span>
                  <span className={
                    result.oil_trend === "rising" ? "text-yellow-400" :
                    result.oil_trend === "falling" ? "text-green-400" : "text-gray-500"
                  }>
                    {" "}{result.oil_trend === "rising" ? "▲" : result.oil_trend === "falling" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {result.vix != null && (
                <span className={`bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 ${
                  result.vix > 20 ? "text-red-400" : result.vix < 15 ? "text-green-400" : "text-gray-300"
                }`}>
                  VIX <span className="font-medium">{result.vix.toFixed(1)}</span>
                  <span className={result.vix_trend === "rising" ? "text-red-400" : result.vix_trend === "falling" ? "text-green-400" : "text-gray-500"}>
                    {" "}{result.vix_trend === "rising" ? "▲" : result.vix_trend === "falling" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {(result.sp500_price != null || result.sp500_change != null) && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  S&P 500 <span className="text-white font-medium">
                    {result.sp500_price != null ? result.sp500_price.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"}
                  </span>
                  {result.sp500_change != null && (
                    <span className={result.sp500_change > 0.1 ? "text-green-400" : result.sp500_change < -0.1 ? "text-red-400" : "text-gray-500"}>
                      {" "}({result.sp500_change > 0 ? "+" : ""}{result.sp500_change.toFixed(2)}%)
                    </span>
                  )}
                  <span className={
                    result.sp500_trend === "risk_on" ? "text-green-400" :
                    result.sp500_trend === "risk_off" ? "text-red-400" : "text-gray-500"
                  }>
                    {" "}{result.sp500_trend === "risk_on" ? "▲" : result.sp500_trend === "risk_off" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {result.gold_price != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  Gold <span className="text-white font-medium">${result.gold_price.toFixed(0)}</span>
                  <span className={result.gold_trend === "rising" ? "text-yellow-400" : result.gold_trend === "falling" ? "text-red-400" : "text-gray-500"}>
                    {" "}{result.gold_trend === "rising" ? "▲" : result.gold_trend === "falling" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {result.ten_year_yield != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  10Y <span className="text-white font-medium">{result.ten_year_yield.toFixed(2)}%</span>
                  <span className={
                    result.ten_year_yield_trend === "rising" ? "text-red-400" :
                    result.ten_year_yield_trend === "falling" ? "text-green-400" : "text-gray-500"
                  }>
                    {" "}{result.ten_year_yield_trend === "rising" ? "▲" : result.ten_year_yield_trend === "falling" ? "▼" : "→"}
                  </span>
                  {result.two_year_yield != null && (
                    <span className="text-gray-500"> · 2Y {result.two_year_yield.toFixed(2)}%</span>
                  )}
                </span>
              )}
              {result.yield_curve_spread != null && (
                <span className={`bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 ${
                  result.yield_curve_spread < 0 ? "text-red-400" : "text-gray-300"
                }`} title="10Y minus 2Y Treasury spread">
                  10Y-2Y <span className="font-medium">{result.yield_curve_spread > 0 ? "+" : ""}{result.yield_curve_spread.toFixed(2)}</span>
                  <span className={result.yield_curve_spread > 0.05 ? "text-green-400" : result.yield_curve_spread < -0.05 ? "text-red-400" : "text-gray-500"}>
                    {" "}{result.yield_curve_spread > 0.05 ? "▲" : result.yield_curve_spread < -0.05 ? "▼" : "→"}
                  </span>
                  {result.yield_curve_spread < 0 && <span className="text-red-400 text-xs"> inverted</span>}
                </span>
              )}
              {result.fed_funds_rate != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300" title={result.fed_rate_type === "target" ? "FOMC target (upper)" : result.fed_rate_type === "effective" ? "Effective rate" : undefined}>
                  Fed Rate <span className="text-white font-medium">{result.fed_funds_rate.toFixed(2)}%</span>
                  <span className={
                    result.fed_rate_trend === "falling" ? "text-green-400" :
                    result.fed_rate_trend === "rising" ? "text-red-400" : "text-gray-500"
                  }>
                    {" "}{result.fed_rate_trend === "falling" ? "▼" : result.fed_rate_trend === "rising" ? "▲" : "→"}
                  </span>
                  {result.fed_rate_stance && (
                    <span className={
                      result.fed_rate_stance === "cutting" ? "text-green-400" :
                      result.fed_rate_stance === "hiking" ? "text-red-400" : "text-yellow-400"
                    }>
                      {" "}{result.fed_rate_stance}
                    </span>
                  )}
                </span>
              )}
              {result.unemployment_rate != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  Unemp <span className="text-white font-medium">{result.unemployment_rate.toFixed(1)}%</span>
                  <span className={result.unemployment_trend === "rising" ? "text-yellow-400" : result.unemployment_trend === "falling" ? "text-green-400" : "text-gray-500"}>
                    {" "}{result.unemployment_trend === "rising" ? "▲" : result.unemployment_trend === "falling" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {result.pmi_value != null && (
                <span
                  className={`bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 ${
                    result.pmi_value < 50 ? "text-red-400" : "text-green-400"
                  }`}
                  title={result.pmi_value >= 50 ? "ISM Manufacturing PMI — expansion" : "ISM Manufacturing PMI — contraction"}
                >
                  PMI <span className="font-medium">{result.pmi_value.toFixed(1)}</span>
                  <span className={
                    result.pmi_trend === "rising" ? "text-green-400" :
                    result.pmi_trend === "falling" ? "text-red-400" : "text-gray-500"
                  }>
                    {" "}{result.pmi_trend === "rising" ? "▲" : result.pmi_trend === "falling" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {result.gdp_growth_rate != null && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300">
                  GDP <span className={`font-medium ${result.gdp_growth_rate < 0 ? "text-red-400" : "text-white"}`}>
                    {result.gdp_growth_rate > 0 ? "+" : ""}{result.gdp_growth_rate.toFixed(1)}%
                  </span>
                  <span className={
                    result.gdp_trend === "accelerating" ? "text-green-400" :
                    result.gdp_trend === "contracting" || result.gdp_trend === "decelerating" ? "text-red-400" : "text-gray-500"
                  }>
                    {" "}{result.gdp_trend === "accelerating" ? "▲" : result.gdp_trend === "contracting" || result.gdp_trend === "decelerating" ? "▼" : "→"}
                  </span>
                </span>
              )}
              {(result.m2_trend || result.m2_change != null) && (
                <span className="bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800 text-gray-300" title={result.m2_yoy_change != null ? `YoY ${result.m2_yoy_change > 0 ? "+" : ""}${result.m2_yoy_change}%` : undefined}>
                  M2 <span className={
                    result.m2_trend === "expanding" || result.m2_trend === "slight expansion" ? "text-green-400 font-medium" :
                    result.m2_trend === "contracting" || result.m2_trend === "slight contraction" ? "text-red-400 font-medium" : "text-gray-400 font-medium"
                  }>
                    {result.m2_trend ?? "—"}
                  </span>
                  <span className={
                    result.m2_trend === "expanding" || result.m2_trend === "slight expansion" ? "text-green-400" :
                    result.m2_trend === "contracting" || result.m2_trend === "slight contraction" ? "text-red-400" : "text-gray-500"
                  }>
                    {" "}{result.m2_trend === "expanding" || result.m2_trend === "slight expansion" ? "▲" :
                      result.m2_trend === "contracting" || result.m2_trend === "slight contraction" ? "▼" : "→"}
                  </span>
                  {result.m2_change != null && (
                    <span className="text-gray-500 text-xs ml-0.5">({result.m2_change > 0 ? "+" : ""}{result.m2_change}%)</span>
                  )}
                </span>
              )}
                </div>

                {/* Key Macro Headlines */}
                {result.top_headlines && result.top_headlines.length > 0 && (
                  <div className="bg-gray-900 rounded-xl p-3 border border-gray-800">
                    <div className="text-[10px] sm:text-xs text-gray-500 mb-1.5">Key Macro Headlines</div>
                    <div className="space-y-1 sm:space-y-1.5">
                      {result.top_headlines.map((hl, i) => (
                        <div key={i} className="flex items-start gap-1.5 text-[11px] sm:text-sm">
                          <span className={`shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-[9px] sm:text-[10px] font-semibold uppercase ${
                            hl.event_bias === "dovish" ? "bg-green-900/50 text-green-400" :
                            hl.event_bias === "hawkish" ? "bg-red-900/50 text-red-400" :
                            "bg-gray-800 text-gray-400"
                          }`}>
                            {hl.event_bias}
                          </span>
                          <span className="text-gray-300 leading-snug min-w-0 flex-1">{hl.title}</span>
                          {hl.source && (
                            <span className="shrink-0 text-gray-600 text-[10px] sm:text-xs">{hl.source}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <p className="text-center text-[10px] sm:text-xs text-gray-600 pt-1">{new Date(result.timestamp).toLocaleString()}</p>
          </>
        )}
      </div>
    </main>
  )
}
