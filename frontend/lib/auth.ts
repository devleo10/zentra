const STORAGE_KEY = "btc_macro_dashboard_token"

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return
  try {
    localStorage.setItem(STORAGE_KEY, token)
  } catch {
    /* ignore */
  }
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export function authFetchHeaders(): HeadersInit {
  const t = getAuthToken()
  if (!t) return {}
  return { Authorization: `Bearer ${t}` }
}
