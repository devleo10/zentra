"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import BtcMacroDashboardNew from "@/components/BtcMacroDashboardNew"
import { getAuthStatus } from "@/lib/api"
import { getAuthToken } from "@/lib/auth"

export default function DashboardPage() {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const status = await getAuthStatus()
        if (cancelled) return
        if (status.auth_required && !getAuthToken()) {
          router.replace("/login?next=/dashboard")
          return
        }
      } catch {
        if (!cancelled) setReady(true)
        return
      }
      if (!cancelled) setReady(true)
    })()
    return () => {
      cancelled = true
    }
  }, [router])

  if (!ready) {
    return (
      <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4">
        <p className="text-gray-400 text-sm">Checking access…</p>
      </main>
    )
  }

  return <BtcMacroDashboardNew />
}
