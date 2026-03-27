"use client"

import { useState, Suspense } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { loginDashboard } from "@/lib/api"
import { setAuthToken } from "@/lib/auth"

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const nextPath = searchParams.get("next") || "/dashboard"

  const [loginId, setLoginId] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await loginDashboard(loginId.trim(), password)
      if (res.auth_required && res.access_token) {
        setAuthToken(res.access_token)
      }
      router.push(nextPath.startsWith("/") ? nextPath : "/dashboard")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold tracking-tight">Log in</h1>
          <p className="text-gray-500 text-sm">
            Sign in to run live macro analysis.
          </p>
        </div>

        <form onSubmit={onSubmit} className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4 shadow-lg">
          <div>
            <label htmlFor="login_id" className="block text-xs text-gray-500 mb-1">
              Login ID
            </label>
            <input
              id="login_id"
              name="login_id"
              autoComplete="username"
              value={loginId}
              onChange={(e) => setLoginId(e.target.value)}
              className="w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-xs text-gray-500 mb-1">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              required
            />
          </div>
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg font-semibold text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-400 transition-colors"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500">
          <Link href="/" className="text-blue-400 hover:text-blue-300">
            ← Back to overview
          </Link>
        </p>
      </div>
    </main>
  )
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
          <p className="text-gray-400 text-sm">Loading…</p>
        </main>
      }
    >
      <LoginForm />
    </Suspense>
  )
}
