/**
 * Typed fetch wrappers for every Box endpoint.
 * Base URL comes from NEXT_PUBLIC_BOX_URL; falls back to localhost:8000.
 */

import type {
  TreeData,
  JokeRecord,
  TraceData,
  ComplianceData,
  FileDetail,
  ExportData,
} from './types'

export const BOX_URL = process.env.NEXT_PUBLIC_BOX_URL ?? 'http://localhost:8000'

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BOX_URL}${path}`)
  if (!res.ok) {
    let reason = `HTTP ${res.status}`
    try {
      const body = await res.json()
      reason = body?.detail?.reason ?? body?.reason ?? body?.detail ?? reason
    } catch {
      // ignore parse errors — use status code
    }
    throw new Error(reason)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Read endpoints
// ---------------------------------------------------------------------------

/** Full hierarchy tree in a single request */
export const fetchTree = (): Promise<TreeData> => apiFetch('/box')

/** Live compliance check — never a stored flag */
export const fetchCompliance = (): Promise<ComplianceData> => apiFetch('/compliance')

/** Single joke record */
export const fetchJoke = (id: string): Promise<JokeRecord> => apiFetch(`/jokes/${id}`)

/** All trace steps for a joke, ordered by timestamp */
export const fetchTrace = (id: string): Promise<TraceData> => apiFetch(`/jokes/${id}/trace`)

/** File with joke summaries */
export const fetchFile = (id: string): Promise<FileDetail> => apiFetch(`/files/${id}`)

/** Full library export */
export const fetchExport = (): Promise<ExportData> => apiFetch('/export')

// ---------------------------------------------------------------------------
// WebSocket helpers
// ---------------------------------------------------------------------------

/**
 * Build the WebSocket URL for a voice session.
 * Replaces http(s) with ws(s) so NEXT_PUBLIC_BOX_URL works for both.
 */
export function getWsUrl(sessionId: string): string {
  const base = BOX_URL.replace(/^https?/, (p) => (p === 'https' ? 'wss' : 'ws'))
  return `${base}/ws/session/${sessionId}`
}
