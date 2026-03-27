"use client"

/**
 * Static marketing preview — no API calls. Numbers are illustrative only.
 */
const SECTION_LABELS: Record<string, string> = {
  inflation: "Inflation",
  economy: "Economy",
  fed_policy: "Fed Policy",
  liquidity: "Liquidity",
  dxy: "US Dollar (DXY)",
  risk_sentiment: "Risk Sentiment",
}

const DEMO_SECTIONS: Record<string, number> = {
  inflation: 22,
  economy: 57,
  fed_policy: 50,
  liquidity: 50,
  dxy: 23,
  risk_sentiment: 40,
}

const scoreColor = (s: number) =>
  s >= 65 ? "text-green-400" : s >= 40 ? "text-yellow-400" : "text-red-400"

const barColor = (s: number) =>
  s >= 65 ? "bg-green-500" : s >= 40 ? "bg-yellow-500" : "bg-red-500"

export default function MarketingDemoDashboard() {
  return (
    <div className="relative rounded-xl border border-amber-700/40 bg-gray-900/80 overflow-hidden">
      <div className="absolute top-2 right-2 z-10">
        <span className="px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wide bg-amber-500/20 text-amber-300 border border-amber-500/40">
          Sample preview
        </span>
      </div>

      <div className="p-4 sm:p-5 space-y-4 pt-10 sm:pt-4">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-3">
            <div className="bg-gray-950/80 rounded-xl p-4 border border-gray-800">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Final verdict (illustrative)</div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold tabular-nums text-white">37</span>
                <span className="text-gray-500 text-sm">/ 100</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 items-center">
                <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-red-600 text-white">Bearish</span>
                <span className="text-gray-400 text-xs">Capital protection</span>
              </div>
              <p className="text-gray-500 text-[11px] mt-2">Confidence 45% (Low) · Warnings 5</p>
              <p className="text-gray-400 text-xs mt-2">BTC <span className="text-white font-mono">$68,447</span></p>
            </div>

            <div className="bg-gray-950/80 rounded-xl p-3 border border-gray-800">
              <div className="text-[10px] text-gray-500 mb-2">Breakdown</div>
              <div className="space-y-1.5">
                {Object.entries(DEMO_SECTIONS).map(([key, score]) => (
                  <div key={key} className="flex items-center gap-2">
                    <span className="text-gray-500 text-[11px] w-24 shrink-0">{SECTION_LABELS[key]}</span>
                    <div className="flex-1 bg-gray-800 rounded-full h-1.5">
                      <div className={`h-1.5 rounded-full ${barColor(score)}`} style={{ width: `${score}%` }} />
                    </div>
                    <span className={`text-[11px] font-semibold w-6 text-right tabular-nums ${scoreColor(score)}`}>{score}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-[10px] text-gray-500 mb-1">Key metrics (sample)</div>
            <div className="grid grid-cols-2 gap-1.5 text-[11px] sm:text-xs">
              {[
                ["CPI MoM", "+0.30%"],
                ["10Y yield", "4.33%"],
                ["VIX", "27.7"],
                ["DXY", "100.0"],
                ["WTI", "$94"],
                ["Fed funds", "3.75%"],
              ].map(([k, v]) => (
                <div key={k} className="bg-gray-950/80 px-2 py-1.5 rounded-lg border border-gray-800 text-gray-400">
                  {k} <span className="text-white font-medium ml-1">{v}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-gray-950/80 rounded-xl p-3 border border-gray-800">
            <div className="text-[10px] text-gray-500 mb-2">Analyst commentary (sample)</div>
            <p className="text-gray-300 text-xs leading-relaxed">
              Macro conditions are shown here as an example layout only. Narrative, scores, and headlines are not
              connected to live data in this preview.
            </p>
            <div className="mt-3 space-y-1 text-[11px]">
              <p><span className="text-red-400 font-medium">Risk:</span> <span className="text-gray-500">Policy surprise example.</span></p>
              <p><span className="text-blue-400 font-medium">Watch:</span> <span className="text-gray-500">Upcoming CPI example.</span></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
