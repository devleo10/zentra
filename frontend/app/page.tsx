import Link from "next/link"
import MarketingDemoDashboard from "@/components/MarketingDemoDashboard"

export default function MarketingHome() {
  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <div className="w-full max-w-[1600px] mx-auto px-3 py-6 sm:px-6 sm:py-10 space-y-8">
        <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div className="space-y-2">
            <h1 className="text-2xl sm:text-4xl font-bold tracking-tight">BTC Macro Signal</h1>
            <p className="text-gray-400 text-sm sm:text-base max-w-xl">
              Deterministic macro scoring, Fed and liquidity context, and headline intelligence — built for Bitcoin
              positioning.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/login"
              className="inline-flex items-center justify-center px-5 py-2.5 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 transition-colors"
            >
              Log in
            </Link>
            <Link
              href="/dashboard"
              className="inline-flex items-center justify-center px-5 py-2.5 rounded-xl font-semibold text-sm border border-gray-600 text-gray-200 hover:bg-gray-900 transition-colors"
            >
              Open dashboard
            </Link>
          </div>
        </header>

        <section className="rounded-2xl border border-gray-800 bg-gray-900/40 p-4 sm:p-6 space-y-3">
          <h2 className="text-lg font-semibold text-white">What you see below is a static preview</h2>
          <p className="text-gray-400 text-sm leading-relaxed max-w-3xl">
            The sample dashboard illustrates layout and signal types only — it does not call your analysis engine or
            live market feeds. To <strong className="text-gray-300">run your own analysis</strong> (refresh data, full
            pipeline, stored snapshots), sign in with the login and password you were given.
          </p>
        </section>

        <MarketingDemoDashboard />

        <section className="text-center py-8 border-t border-gray-800">
          <p className="text-gray-500 text-sm mb-4">Ready to run live macro analysis?</p>
          <Link
            href="/login"
            className="inline-flex items-center justify-center px-6 py-3 rounded-xl font-semibold text-sm bg-blue-600 hover:bg-blue-500 transition-colors"
          >
            Log in to run analysis
          </Link>
          <p className="text-gray-600 text-xs mt-4">
            After login, use <span className="text-gray-400">Run analysis</span> on the dashboard to execute the full engine.
          </p>
        </section>
      </div>
    </main>
  )
}
