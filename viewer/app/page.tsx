'use client'

import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchTree, fetchCompliance } from '@/lib/api'
import type { SelectionPath } from '@/lib/types'

import ComplianceBar from '@/components/ComplianceBar'
import Tree from '@/components/Tree'
import JokeDetail from '@/components/JokeDetail'
import Trace from '@/components/Trace'
import Export from '@/components/Export'
import QuerySlot from '@/components/QuerySlot'

export default function Home() {
  const qc = useQueryClient()

  // ---------------------------------------------------------------------------
  // Selection state — shared across all three panes
  // ---------------------------------------------------------------------------
  const [selectedJokeId, setSelectedJokeId] = useState<string | null>(null)
  const [selectionPath, setSelectionPath] = useState<SelectionPath | null>(null)

  // ---------------------------------------------------------------------------
  // Compliance filter
  // ---------------------------------------------------------------------------
  const [violationFilter, setViolationFilter] = useState(false)

  // ---------------------------------------------------------------------------
  // WebSocket / Query Slot session state
  // ---------------------------------------------------------------------------
  const [wsConnected, setWsConnected] = useState(false)

  // ---------------------------------------------------------------------------
  // Remote data
  // ---------------------------------------------------------------------------
  const { data: tree } = useQuery({ queryKey: ['tree'], queryFn: fetchTree })
  const { data: compliance } = useQuery({
    queryKey: ['compliance'],
    queryFn: fetchCompliance,
    refetchInterval: 60_000,
  })

  // ---------------------------------------------------------------------------
  // Selection handler — called by Tree and QuerySlot
  // ---------------------------------------------------------------------------
  const handleSelectJoke = useCallback(
    (id: string, path?: SelectionPath) => {
      setSelectedJokeId(id)
      if (path) setSelectionPath(path)
    },
    [],
  )

  // ---------------------------------------------------------------------------
  // After a voice session ends, refresh tree + compliance so new jokes appear
  // ---------------------------------------------------------------------------
  const handleSessionEnd = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['tree'] })
    void qc.invalidateQueries({ queryKey: ['compliance'] })
  }, [qc])

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-base text-hi relative z-0">
      {/* ─── Header bar ─────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-4 px-4 h-11 shrink-0 bg-surface border-b border-edge z-10 relative">
        {/* ON AIR indicator */}
        {wsConnected && (
          <div className="flex items-center gap-1.5">
            <span className="on-air w-2 h-2 rounded-full bg-red-500 block" />
            <span className="font-display text-xs tracking-widest text-red-400 font-semibold">
              ON AIR
            </span>
          </div>
        )}

        <h1 className="font-display text-xl font-bold tracking-[0.15em] text-hi uppercase select-none">
          Jokebox
        </h1>

        <span className="text-edge select-none">·</span>

        <ComplianceBar
          compliance={compliance}
          filtered={violationFilter}
          onToggleFilter={() => setViolationFilter((f) => !f)}
        />

        <div className="ml-auto">
          <Export selectedJokeId={selectedJokeId} selectedJoke={null} />
        </div>
      </header>

      {/* ─── Three-pane body ─────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left — tree */}
        <aside className="w-72 shrink-0 flex flex-col border-r border-edge overflow-hidden">
          <Tree
            tree={tree}
            compliance={compliance}
            violationFilter={violationFilter}
            selectedJokeId={selectedJokeId}
            onSelectJoke={handleSelectJoke}
          />
        </aside>

        {/* Center — joke detail */}
        <main className="flex-1 overflow-y-auto min-w-0">
          <JokeDetail
            jokeId={selectedJokeId}
            selectionPath={selectionPath}
            tree={tree}
          />
        </main>

        {/* Right — query slot + trace */}
        <aside className="w-[22rem] shrink-0 flex flex-col border-l border-edge overflow-hidden">
          <QuerySlot
            onSelectJoke={handleSelectJoke}
            onConnectionChange={setWsConnected}
            onSessionEnd={handleSessionEnd}
          />
          <div className="flex-1 overflow-y-auto border-t border-edge">
            <Trace jokeId={selectedJokeId} />
          </div>
        </aside>
      </div>
    </div>
  )
}
