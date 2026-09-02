'use client'

import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchFile } from '@/lib/api'
import type {
  TreeData,
  TreeCabinet,
  TreeDrawer,
  TreeFile,
  ComplianceData,
  JokeSummary,
  SelectionPath,
} from '@/lib/types'

// ---------------------------------------------------------------------------
// Violation path helpers
// ---------------------------------------------------------------------------

function buildViolationSet(compliance: ComplianceData | undefined): Set<string> {
  if (!compliance) return new Set()
  return new Set(compliance.violations.map((v) => v.path))
}

/** True if this cabinet or any of its descendants has a violation. */
function cabHasViolation(cab: TreeCabinet, vPaths: Set<string>): boolean {
  if (vPaths.has(cab.label)) return true
  return cab.drawers.some((d) => drwHasViolation(cab.label, d, vPaths))
}

/** True if this drawer or any of its files has a violation. */
function drwHasViolation(cabLabel: string, drw: TreeDrawer, vPaths: Set<string>): boolean {
  const key = `${cabLabel} > ${drw.label}`
  if (vPaths.has(key)) return true
  return drw.files.some((f) => vPaths.has(`${key} > ${f.label}`))
}

// ---------------------------------------------------------------------------
// Score dot — colour-coded
// ---------------------------------------------------------------------------
function ScoreDot({ score }: { score: number }) {
  const color =
    score >= 9
      ? 'bg-emerald-400'
      : score >= 7
        ? 'bg-green-500'
        : score >= 5
          ? 'bg-yellow-400'
          : score >= 3
            ? 'bg-orange-400'
            : 'bg-red-500'
  return <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${color}`} />
}

// ---------------------------------------------------------------------------
// Violation marker
// ---------------------------------------------------------------------------
function VioMark({ tainted, direct }: { tainted: boolean; direct: boolean }) {
  if (!tainted && !direct) return null
  return (
    <span
      title={direct ? 'Compliance violation' : 'Descendant has violation'}
      className={`text-[8px] font-mono font-bold leading-none rounded px-0.5 ${
        direct
          ? 'text-violation border border-violation/50 bg-violation/10'
          : 'text-violation/50 border border-violation/20'
      }`}
    >
      !
    </span>
  )
}

// ---------------------------------------------------------------------------
// Joke row (leaf level)
// ---------------------------------------------------------------------------
interface JokeRowProps {
  joke: JokeSummary
  idx: number
  selected: boolean
  onSelect: () => void
}

function JokeRow({ joke, idx, selected, onSelect }: JokeRowProps) {
  return (
    <button
      onClick={onSelect}
      className={[
        'w-full flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono cursor-pointer transition-colors duration-100',
        selected
          ? 'bg-accent/10 border-l-2 border-accent text-hi pl-1.5'
          : 'text-lo hover:text-mid hover:bg-raised',
      ].join(' ')}
    >
      <ScoreDot score={joke.score} />
      <span className="truncate text-[10px]">{idx + 1}. {joke.id.slice(0, 8)}…</span>
      <span className="ml-auto text-[9px] text-lo/70">{joke.score}/10</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// File node (expands to show jokes)
// ---------------------------------------------------------------------------
interface FileNodeProps {
  file: TreeFile
  cabLabel: string
  drwLabel: string
  selectedJokeId: string | null
  onSelectJoke: (id: string, path: SelectionPath) => void
  vPaths: Set<string>
}

function FileNode({
  file,
  cabLabel,
  drwLabel,
  selectedJokeId,
  onSelectJoke,
  vPaths,
}: FileNodeProps) {
  const [open, setOpen] = useState(false)
  const filePath = `${cabLabel} > ${drwLabel} > ${file.label}`
  const isDirect = vPaths.has(filePath)

  const { data: detail, isFetching } = useQuery({
    queryKey: ['file', file.id],
    queryFn: () => fetchFile(file.id),
    enabled: open,
    staleTime: 60_000,
  })

  const handleFileClick = () => {
    setOpen((o) => !o)
    // Auto-select first joke when opening if none selected
    if (!open && detail?.jokes.length) {
      const first = detail.jokes[0]
      onSelectJoke(first.id, { cabinet: cabLabel, drawer: drwLabel, file: file.label })
    }
  }

  const isChildSelected = detail?.jokes.some((j) => j.id === selectedJokeId)

  return (
    <div>
      <button
        onClick={handleFileClick}
        className={[
          'w-full flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono transition-colors duration-100',
          open || isChildSelected
            ? 'text-hi bg-raised'
            : 'text-lo hover:text-mid hover:bg-raised/50',
        ].join(' ')}
      >
        <span className="text-[8px] text-lo/50">{open ? '▾' : '▸'}</span>
        <VioMark tainted={isDirect} direct={isDirect} />
        <span className="truncate flex-1 text-left">{file.label}</span>
        <span
          className={[
            'text-[9px] ml-auto px-1 rounded tabular-nums',
            file.joke_count < 2 ? 'text-violation/80' : 'text-lo/60',
          ].join(' ')}
          title={`${file.joke_count} joke${file.joke_count !== 1 ? 's' : ''}`}
        >
          {file.joke_count}
        </span>
      </button>

      {open && (
        <div className="ml-3 pl-2 border-l border-edge/50 mt-0.5 mb-0.5 space-y-0.5">
          {isFetching && !detail && (
            <div className="text-[9px] font-mono text-lo/50 px-2 py-1 animate-pulse">
              Loading…
            </div>
          )}
          {detail?.jokes.map((joke, i) => (
            <JokeRow
              key={joke.id}
              joke={joke}
              idx={i}
              selected={selectedJokeId === joke.id}
              onSelect={() =>
                onSelectJoke(joke.id, { cabinet: cabLabel, drawer: drwLabel, file: file.label })
              }
            />
          ))}
          {detail?.jokes.length === 0 && (
            <div className="text-[9px] font-mono text-violation/70 px-2 py-1">No jokes filed</div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drawer node
// ---------------------------------------------------------------------------
interface DrawerNodeProps {
  drw: TreeDrawer
  cabLabel: string
  selectedJokeId: string | null
  onSelectJoke: (id: string, path: SelectionPath) => void
  vPaths: Set<string>
  violationFilter: boolean
}

function DrawerNode({
  drw,
  cabLabel,
  selectedJokeId,
  onSelectJoke,
  vPaths,
  violationFilter,
}: DrawerNodeProps) {
  const [open, setOpen] = useState(false)
  const key = `${cabLabel} > ${drw.label}`
  const isDirect = vPaths.has(key)
  const isTainted = isDirect || drw.files.some((f) => vPaths.has(`${key} > ${f.label}`))

  const visibleFiles = violationFilter
    ? drw.files.filter((f) => vPaths.has(`${key} > ${f.label}`))
    : drw.files

  if (violationFilter && !isTainted) return null

  const fileCount = drw.files.length

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className={[
          'w-full flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono transition-colors duration-100',
          open ? 'text-hi' : 'text-mid hover:text-hi hover:bg-raised/50',
        ].join(' ')}
      >
        <span className="text-[8px] text-lo/50">{open ? '▾' : '▸'}</span>
        <VioMark tainted={isTainted} direct={isDirect} />
        <span className="truncate flex-1 text-left">{drw.label}</span>
        <span
          className={[
            'text-[9px] ml-auto px-1 rounded tabular-nums',
            fileCount < 2 ? 'text-violation/80' : 'text-lo/60',
          ].join(' ')}
          title={`${fileCount} file${fileCount !== 1 ? 's' : ''}`}
        >
          {fileCount}
        </span>
      </button>

      {open && (
        <div className="ml-3 pl-2 border-l border-edge/50 mt-0.5 mb-1 space-y-0.5">
          {visibleFiles.map((f) => (
            <FileNode
              key={f.id}
              file={f}
              cabLabel={cabLabel}
              drwLabel={drw.label}
              selectedJokeId={selectedJokeId}
              onSelectJoke={onSelectJoke}
              vPaths={vPaths}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cabinet node
// ---------------------------------------------------------------------------
interface CabinetNodeProps {
  cab: TreeCabinet
  selectedJokeId: string | null
  onSelectJoke: (id: string, path: SelectionPath) => void
  vPaths: Set<string>
  violationFilter: boolean
}

function CabinetNode({
  cab,
  selectedJokeId,
  onSelectJoke,
  vPaths,
  violationFilter,
}: CabinetNodeProps) {
  const [open, setOpen] = useState(true)
  const isDirect = vPaths.has(cab.label)
  const isTainted = cabHasViolation(cab, vPaths)

  if (violationFilter && !isTainted) return null

  const drwCount = cab.drawers.length

  return (
    <div className="mb-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className={[
          'w-full flex items-center gap-1.5 px-2 py-1.5 rounded text-xs',
          'font-display uppercase tracking-wider font-semibold transition-colors duration-100',
          open ? 'text-hi' : 'text-mid hover:text-hi hover:bg-raised/50',
        ].join(' ')}
      >
        <span className="text-[8px] text-lo/50">{open ? '▾' : '▸'}</span>
        <VioMark tainted={isTainted} direct={isDirect} />
        <span className="truncate flex-1 text-left">{cab.label}</span>
        <span
          className={[
            'text-[9px] font-mono ml-auto px-1 rounded tabular-nums',
            drwCount < 2 ? 'text-violation/80' : 'text-lo/60',
          ].join(' ')}
          title={`${drwCount} drawer${drwCount !== 1 ? 's' : ''}`}
        >
          {drwCount}
        </span>
      </button>

      {open && (
        <div className="ml-2 space-y-0.5">
          {cab.drawers.map((d) => (
            <DrawerNode
              key={d.id}
              drw={d}
              cabLabel={cab.label}
              selectedJokeId={selectedJokeId}
              onSelectJoke={onSelectJoke}
              vPaths={vPaths}
              violationFilter={violationFilter}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tree root
// ---------------------------------------------------------------------------
interface TreeProps {
  tree: TreeData | undefined
  compliance: ComplianceData | undefined
  violationFilter: boolean
  selectedJokeId: string | null
  onSelectJoke: (id: string, path: SelectionPath) => void
}

export default function Tree({
  tree,
  compliance,
  violationFilter,
  selectedJokeId,
  onSelectJoke,
}: TreeProps) {
  const vPaths = useMemo(() => buildViolationSet(compliance), [compliance])

  if (!tree) {
    return (
      <div className="p-4 space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-6 rounded bg-raised animate-pulse" />
        ))}
      </div>
    )
  }

  const visibleCabinets = violationFilter
    ? tree.cabinets.filter((c) => cabHasViolation(c, vPaths))
    : tree.cabinets

  return (
    <div className="flex-1 overflow-y-auto p-2 space-y-1">
      {/* Summary row */}
      <div className="px-2 pb-1 mb-1 border-b border-edge flex items-center gap-2">
        <span className="font-mono text-[9px] text-lo uppercase tracking-widest">
          Archive
        </span>
        <span className="font-mono text-[9px] text-lo/50">
          {tree.cabinets.length}c · {tree.cabinets.reduce((a, c) => a + c.drawers.length, 0)}d
        </span>
        {violationFilter && (
          <span className="ml-auto text-[9px] font-mono text-violation/70">filtered</span>
        )}
      </div>

      {visibleCabinets.length === 0 && (
        <div className="px-2 py-4 text-center text-[10px] font-mono text-lo">
          {violationFilter ? 'No violations found.' : 'Archive is empty.'}
        </div>
      )}

      {visibleCabinets.map((cab) => (
        <CabinetNode
          key={cab.id}
          cab={cab}
          selectedJokeId={selectedJokeId}
          onSelectJoke={onSelectJoke}
          vPaths={vPaths}
          violationFilter={violationFilter}
        />
      ))}
    </div>
  )
}
