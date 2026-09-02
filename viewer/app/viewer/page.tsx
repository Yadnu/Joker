'use client'

/**
 * /viewer — The Archive.
 * Full three-pane archive UI: tree + joke detail + trace.
 * Supports ?joke=<id> deep link from the Critic's card feed.
 */

import { useState, useCallback, useEffect, useMemo, Suspense } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { fetchTree, fetchCompliance } from '@/lib/api'
import type { SelectionPath } from '@/lib/types'
import { pickFirstArchiveJoke, treeWithoutSeedJokes } from '@/lib/archive'

import ComplianceBar from '@/components/ComplianceBar'
import Tree from '@/components/Tree'
import JokeDetail from '@/components/JokeDetail'
import Trace from '@/components/Trace'
import Export from '@/components/Export'
import QuerySlot from '@/components/QuerySlot'

// ---------------------------------------------------------------------------
// Deep-link reader — sets the initial selected joke from ?joke= query param.
// Requires Suspense because useSearchParams is async in App Router.
// ---------------------------------------------------------------------------

function DeepLinkLoader({ onLoad }: { onLoad: (id: string) => void }) {
  const searchParams = useSearchParams()
  const jokeId = searchParams.get('joke')

  useEffect(() => {
    if (jokeId) onLoad(jokeId)
  }, [jokeId, onLoad])

  return null
}

// ---------------------------------------------------------------------------
// Archive page
// ---------------------------------------------------------------------------

export default function ViewerPage() {
  const qc = useQueryClient()

  const [selectedJokeId, setSelectedJokeId] = useState<string | null>(null)
  const [selectionPath, setSelectionPath] = useState<SelectionPath | null>(null)
  const [violationFilter, setViolationFilter] = useState(false)
  const [wsConnected, setWsConnected] = useState(false)

  const { data: tree, isError: treeFailed, error: treeError } = useQuery({
    queryKey: ['tree'],
    queryFn: fetchTree,
  })
  const { data: compliance, isError: complianceFailed, error: complianceError } = useQuery({
    queryKey: ['compliance'],
    queryFn: fetchCompliance,
    refetchInterval: 60_000,
  })

  const browseTree = useMemo(
    () => (tree ? treeWithoutSeedJokes(tree) : undefined),
    [tree],
  )

  const handleSelectJoke = useCallback(
    (id: string, path?: SelectionPath) => {
      setSelectedJokeId(id)
      if (path) setSelectionPath(path)
    },
    [],
  )

  useEffect(() => {
    if (selectedJokeId || !browseTree) return
    const first = pickFirstArchiveJoke(browseTree)
    if (first) handleSelectJoke(first.id, first.path)
  }, [browseTree, selectedJokeId, handleSelectJoke])

  const handleSessionEnd = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['tree'] })
    void qc.invalidateQueries({ queryKey: ['compliance'] })
  }, [qc])

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-base text-hi relative z-0">
      {/* Deep-link initialiser */}
      <Suspense fallback={null}>
        <DeepLinkLoader onLoad={setSelectedJokeId} />
      </Suspense>

      {/* ─── Header ─────────────────────────────────────────────────────────── */}
      <header className="flex items-start gap-4 px-4 py-1.5 min-h-11 shrink-0 bg-surface border-b border-edge z-10 relative">
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

        <div className="ml-auto flex items-center gap-3">
          <Export selectedJokeId={selectedJokeId} selectedJoke={null} />

          {/* Back to the show */}
          <Link href="/" className="btn text-[11px] tracking-wider">
            ← Back to the show
          </Link>
        </div>
      </header>

      {/* ─── Three-pane body ─────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left — tree */}
        <aside className="w-72 shrink-0 flex flex-col border-r border-edge overflow-hidden">
          {treeFailed && (
            <div className="m-2 px-2 py-1.5 font-mono text-[10px] text-violation/90 bg-violation/10 border border-violation/30 rounded">
              Archive failed to load
              {treeError instanceof Error ? `: ${treeError.message}` : '.'}
            </div>
          )}
          {complianceFailed && (
            <div className="mx-2 mb-1 px-2 py-1.5 font-mono text-[10px] text-violation/90 bg-violation/10 border border-violation/30 rounded">
              Compliance check failed
              {complianceError instanceof Error ? `: ${complianceError.message}` : '.'}
            </div>
          )}
          <Tree
            tree={browseTree}
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
            tree={browseTree}
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
