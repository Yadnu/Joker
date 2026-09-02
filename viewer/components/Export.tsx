'use client'

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { fetchJoke, BOX_URL } from '@/lib/api'
import type { JokeRecord, ExportData } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function downloadBlob(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Convert an array of flat row objects to CSV.
 * Nested fields are serialized as JSON strings; this is noted in the header.
 */
function toCSV(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return '# No data\n'

  const headers = Object.keys(rows[0])
  const nestedFields = headers.filter((h) =>
    ['prompt_responses', 'metadata', 'user_context', 'attribution', 'provenance', 'set_id'].includes(h),
  )

  const comment =
    `# Jokebox library export — ${new Date().toISOString()}\n` +
    `# Nested fields serialized as JSON strings: ${nestedFields.join(', ')}\n`

  const headerRow = headers.map((h) => `"${h}"`).join(',')

  const dataRows = rows.map((row) =>
    headers
      .map((h) => {
        const val = row[h]
        if (val === null || val === undefined) return '""'
        const str = typeof val === 'object' ? JSON.stringify(val) : String(val)
        return `"${str.replace(/"/g, '""')}"`
      })
      .join(','),
  )

  return [comment, headerRow, ...dataRows].join('\n')
}

function jokeToFlatRow(joke: JokeRecord, cabinet?: string, drawer?: string, file?: string) {
  return {
    joke_id: joke.id,
    file_id: joke.file_id,
    cabinet: cabinet ?? '',
    drawer: drawer ?? '',
    file: file ?? '',
    joke_text: joke.joke_text,
    category: joke.category,
    score: joke.score,
    user_reaction: joke.user_reaction,
    prompt_responses: joke.prompt_responses,
    metadata: joke.metadata,
    user_context: joke.user_context,
    attribution: joke.attribution,
    provenance: joke.provenance,
    set_id: joke.set_id,
  }
}

function flattenLibrary(data: ExportData): ReturnType<typeof jokeToFlatRow>[] {
  const rows: ReturnType<typeof jokeToFlatRow>[] = []
  for (const cab of data.cabinets) {
    for (const drw of cab.drawers) {
      for (const file of drw.files) {
        for (const joke of file.jokes) {
          rows.push(jokeToFlatRow(joke, cab.label, drw.label, file.label))
        }
      }
    }
  }
  return rows
}

// ---------------------------------------------------------------------------
// Export button
// ---------------------------------------------------------------------------

interface ExportBtnProps {
  label: string
  title: string
  disabled?: boolean
  loading?: boolean
  onClick: () => Promise<void>
}

function ExportBtn({ label, title, disabled, loading, onClick }: ExportBtnProps) {
  const [running, setRunning] = useState(false)

  const handleClick = async () => {
    if (running) return
    setRunning(true)
    try {
      await onClick()
    } finally {
      setRunning(false)
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={disabled || running}
      title={title}
      className="btn text-[10px] uppercase tracking-wider"
    >
      {running ? '…' : label}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

interface Props {
  selectedJokeId: string | null
  /** Pre-fetched joke, or null if not yet available */
  selectedJoke: JokeRecord | null
}

export default function Export({ selectedJokeId, selectedJoke: _ }: Props) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const loadCurrentJoke = async (): Promise<JokeRecord> => {
    if (!selectedJokeId) throw new Error('No joke selected.')
    const cached = qc.getQueryData<JokeRecord>(['joke', selectedJokeId])
    if (cached) return cached
    return fetchJoke(selectedJokeId)
  }

  // Current joke — JSON
  const handleCurrentJson = async () => {
    setError(null)
    const joke = await loadCurrentJoke()
    downloadBlob(
      JSON.stringify(joke, null, 2),
      `joke-${joke.id}.json`,
      'application/json',
    )
  }

  // Current joke — CSV
  const handleCurrentCsv = async () => {
    setError(null)
    const joke = await loadCurrentJoke()
    const row = jokeToFlatRow(joke)
    downloadBlob(toCSV([row]), `joke-${joke.id}.csv`, 'text/csv')
  }

  // Library — JSON
  const handleLibraryJson = async () => {
    setError(null)
    const res = await fetch(`${BOX_URL}/export`)
    if (!res.ok) throw new Error(`Library export failed: HTTP ${res.status}`)
    const data: ExportData = await res.json()
    downloadBlob(JSON.stringify(data, null, 2), 'jokebox-library.json', 'application/json')
  }

  // Library — CSV
  const handleLibraryCsv = async () => {
    setError(null)
    const res = await fetch(`${BOX_URL}/export`)
    if (!res.ok) throw new Error(`Library export failed: HTTP ${res.status}`)
    const data: ExportData = await res.json()
    const rows = flattenLibrary(data)
    downloadBlob(toCSV(rows), 'jokebox-library.csv', 'text/csv')
  }

  const wrap = (fn: () => Promise<void>) => async () => {
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed.')
    }
  }

  return (
    <div className="flex flex-col items-end gap-0.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[9px] text-lo/50 uppercase tracking-wider mr-0.5">
          Export
        </span>

        <ExportBtn
          label="JSON"
          title="Current joke as JSON"
          disabled={!selectedJokeId}
          onClick={wrap(handleCurrentJson)}
        />
        <ExportBtn
          label="CSV"
          title="Current joke as CSV"
          disabled={!selectedJokeId}
          onClick={wrap(handleCurrentCsv)}
        />

        <span className="text-edge/60 text-xs select-none">|</span>

        <ExportBtn
          label="Lib JSON"
          title="Whole library as JSON (fetched fresh from Box)"
          onClick={wrap(handleLibraryJson)}
        />
        <ExportBtn
          label="Lib CSV"
          title="Whole library as CSV (nested fields are JSON strings)"
          onClick={wrap(handleLibraryCsv)}
        />
      </div>
      {error && (
        <span className="font-mono text-[9px] text-violation/80 max-w-xs text-right">
          {error}
        </span>
      )}
    </div>
  )
}
