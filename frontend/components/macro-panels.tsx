"use client"

import type { TimeFrame, V2AnalysisResult } from "@/lib/api"

/** Numeric up = green ▲, down = red ▼ (consistent across macro tiles). */
export function DeltaArrow({
  delta,
  eps = 0.05,
  className = "",
}: {
  delta: number | null | undefined
  eps?: number
  className?: string
}) {
  if (delta == null || Number.isNaN(delta)) {
    return <span className={`text-gray-500${className ? ` ${className}` : ""}`}>→</span>
  }
  if (delta > eps) {
    return <span className={`text-green-400${className ? ` ${className}` : ""}`}>▲</span>
  }
  if (delta < -eps) {
    return <span className={`text-red-400${className ? ` ${className}` : ""}`}>▼</span>
  }
  return <span className={`text-gray-500${className ? ` ${className}` : ""}`}>→</span>
}

export function TrendArrow({
  trend,
  className = "",
}: {
  trend: string | null | undefined
  className?: string
}) {
  const t = (trend ?? "").toLowerCase()
  if (
    t === "rising" ||
    t === "risk_on" ||
    t === "accelerating" ||
    t === "expanding" ||
    t === "steepening" ||
    t === "strengthening" ||
    t.includes("expansion")
  ) {
    return <span className={`text-green-400${className ? ` ${className}` : ""}`}>▲</span>
  }
  if (
    t === "falling" ||
    t === "risk_off" ||
    t === "contracting" ||
    t === "decelerating" ||
    t === "weakening" ||
    t === "inverted" ||
    t.includes("contraction")
  ) {
    return <span className={`text-red-400${className ? ` ${className}` : ""}`}>▼</span>
  }
  return <span className={`text-gray-500${className ? ` ${className}` : ""}`}>→</span>
}

export function CpiPanel({ result }: { result: V2AnalysisResult }) {
  if (result.cpi_mom_change == null && result.cpi_mom_avg_3m == null) return null
  const avg = result.cpi_mom_avg_3m
  const prior = result.cpi_mom_avg_3m_prior
  const tr = result.cpi_mom_avg_3m_trend

  return (
    <div className="bg-gray-900 rounded-xl p-3 border border-gray-800 text-xs sm:text-sm text-gray-300">
      <div className="text-[10px] sm:text-xs text-gray-500 mb-1.5">CPI (inflation)</div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 items-baseline">
        {result.cpi_mom_change != null && (
          <span>
            MoM{" "}
            <span className="text-white font-medium">
              {result.cpi_mom_change > 0 ? "+" : ""}
              {result.cpi_mom_change.toFixed(2)}%
            </span>
            <span className="ml-0.5">
              <DeltaArrow delta={result.cpi_mom_change} eps={0.02} />
            </span>
          </span>
        )}
        {avg != null && (
          <span title={prior != null ? `Prior 3-mo avg MoM: ${prior.toFixed(3)}%` : undefined}>
            3-mo avg MoM{" "}
            <span className="text-white font-medium">
              {avg > 0 ? "+" : ""}
              {avg.toFixed(3)}%
            </span>
            <span className="ml-0.5">
              <TrendArrow trend={tr} />
            </span>
          </span>
        )}
        {result.cpi_yoy_rate != null && (
          <span className="text-gray-500">YoY {result.cpi_yoy_rate.toFixed(1)}%</span>
        )}
      </div>
    </div>
  )
}

export function UnemploymentPanel({ result, timeframe }: { result: V2AnalysisResult; timeframe: TimeFrame }) {
  if (result.unemployment_rate == null) return null
  const use3m = timeframe === "month" && result.unemployment_trend_3m
  const trend = use3m ? result.unemployment_trend_3m : result.unemployment_trend
  const hist = result.unemployment_history_3

  return (
    <div className="bg-gray-900 rounded-xl p-3 border border-gray-800 text-xs sm:text-sm text-gray-300">
      <div className="text-[10px] sm:text-xs text-gray-500 mb-1.5">
        Unemployment{use3m ? " (3-mo trend)" : ""}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 items-baseline">
        <span>
          Latest{" "}
          <span className="text-white font-medium">{result.unemployment_rate.toFixed(1)}%</span>
          <span className="ml-0.5">
            <TrendArrow trend={trend} />
          </span>
        </span>
        {result.unemployment_3m_avg != null && (
          <span className="text-gray-400">
            3-mo avg <span className="text-white font-medium">{result.unemployment_3m_avg.toFixed(2)}%</span>
          </span>
        )}
      </div>
      {hist && hist.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-800 text-[11px] text-gray-500">
          <span className="text-gray-600">Past months: </span>
          {hist.map((h, i) => (
            <span key={h.date}>
              {i > 0 ? " · " : ""}
              {h.date.slice(0, 7)} <span className="text-gray-300">{h.rate}%</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

type YieldMonth = { date: string; yield_10y: number; yield_2y: number; spread: number }

export function YieldSpreadPanel({ result }: { result: V2AnalysisResult }) {
  const track = result.yield_monthly_track as YieldMonth[] | null | undefined
  if (!track?.length && result.yield_curve_spread == null) return null

  return (
    <div className="bg-gray-900 rounded-xl p-3 border border-gray-800 text-xs sm:text-sm text-gray-300">
      <div className="text-[10px] sm:text-xs text-gray-500 mb-1.5">Treasury 10Y − 2Y (past 3 month-ends)</div>
      {result.yield_curve_spread != null && (
        <div className="mb-2">
          Current spread{" "}
          <span className={`font-medium ${result.yield_curve_spread < 0 ? "text-red-400" : "text-white"}`}>
            {result.yield_curve_spread > 0 ? "+" : ""}
            {result.yield_curve_spread.toFixed(2)}
          </span>
          {result.yield_spread_delta_3m != null && (
            <span className="text-gray-500 ml-2">
              Δ 3m: {result.yield_spread_delta_3m > 0 ? "+" : ""}
              {result.yield_spread_delta_3m.toFixed(2)}
              <span className="ml-0.5">
                <TrendArrow trend={result.yield_spread_trend_3m} />
              </span>
            </span>
          )}
        </div>
      )}
      {track && track.length > 0 && (
        <div className="space-y-1 text-[11px]">
          {track.map((row) => (
            <div key={row.date} className="flex flex-wrap gap-x-3 text-gray-400">
              <span className="text-gray-500 w-[88px] shrink-0">{row.date}</span>
              <span>
                10Y <span className="text-white tabular-nums">{row.yield_10y.toFixed(2)}%</span>
              </span>
              <span>
                2Y <span className="text-white tabular-nums">{row.yield_2y.toFixed(2)}%</span>
              </span>
              <span>
                spr <span className="text-white tabular-nums">{row.spread > 0 ? "+" : ""}{row.spread.toFixed(2)}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function BitcoinMarketPanel({ result }: { result: V2AnalysisResult }) {
  const has =
    result.btc_dominance != null ||
    result.btc_ma200 != null ||
    result.btc_etf_volume != null ||
    result.btc_price != null
  if (!has) return null

  return (
    <div className="bg-gray-900 rounded-xl p-3 border border-gray-800">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="text-[10px] sm:text-xs text-gray-500">Bitcoin market structure</div>
        {result.btc_market_arrow && (
          <span
            className={result.btc_market_arrow === "up" ? "text-green-400 text-sm" : "text-red-400 text-sm"}
            title={result.btc_market_arrow === "up" ? "Price vs 200d MA — above" : "Price vs 200d MA — below"}
          >
            {result.btc_market_arrow === "up" ? "▲" : "▼"}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] sm:text-sm text-gray-300">
        {result.btc_dominance != null && (
          <span>
            BTC.D <span className="text-white font-medium">{result.btc_dominance.toFixed(1)}%</span>
          </span>
        )}
        {result.stablecoin_dominance != null && (
          <span>
            Stable.D <span className="text-white font-medium">{result.stablecoin_dominance.toFixed(1)}%</span>
          </span>
        )}
        {result.btc_ma200 != null && result.btc_price != null && (
          <span>
            200d MA <span className="text-white font-medium">${result.btc_ma200.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            <span className={result.btc_price > result.btc_ma200 ? "text-green-400" : "text-red-400"}>
              {" "}
              {result.btc_price > result.btc_ma200 ? "above ▲" : "below ▼"}
            </span>
          </span>
        )}
        {result.btc_realized_vol_30d != null && (
          <span>
            30d Vol <span className="text-white font-medium">{(result.btc_realized_vol_30d * 100).toFixed(0)}%</span>
          </span>
        )}
        {result.btc_etf_volume != null && (
          <span>
            ETF Vol <span className="text-white font-medium">{(result.btc_etf_volume / 1_000_000).toFixed(0)}M</span>
            <span
              className={
                result.btc_etf_flow_level === "high"
                  ? "text-green-400"
                  : result.btc_etf_flow_level === "low"
                    ? "text-red-400"
                    : "text-gray-500"
              }
            >
              {" "}
              ({result.btc_etf_flow_level ?? "—"})
            </span>
            <span className="ml-0.5">
              <TrendArrow
                trend={
                  result.btc_etf_flow_level === "high"
                    ? "rising"
                    : result.btc_etf_flow_level === "low"
                      ? "falling"
                      : "stable"
                }
              />
            </span>
          </span>
        )}
      </div>
    </div>
  )
}
