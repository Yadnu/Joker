'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTrace } from '@/lib/api'
import type { TraceStep } from '@/lib/types'

// ---------------------------------------------------------------------------
// Kind → accent colour mapping (left-rule)
// ---------------------------------------------------------------------------

const KIND_ACCENT: Record<string, string> = {
  generation: 'border-violet-500',
  classification: 'border-blue-400',
  scoring: 'border-accent',
  delivery: 'border-emerald-500',
  filing: 'border-teal-400',
  suggestion: 'border-slate-400',
  placement: 'border-indigo-400',
  reaction_capture: 'border-rose-400',
  category_creation: 'border-orange-400',
  set_construction: 'border-cyan-400',
  set_adaptation: 'border-yellow-400',
}

const KIND_TEXT: Record<string, string> = {
  generation: 'text-violet-400',
  classification: 'text-blue-400',
  scoring: 'text-accent',
  delivery: 'text-emerald-400',
  filing: 'text-teal-400',
  suggestion: 'text-slate-400',
  placement: 'text-indigo-400',
  reaction_capture: 'text-rose-400',
  category_creation: 'text-orange-400',
  set_construction: 'text-cyan-400',
  set_adaptation: 'text-yellow-400',
}

// ---------------------------------------------------------------------------
// Latency badge
// ---------------------------------------------------------------------------

function LatencyBadge({ ms }: { ms: number }) {
  const color = ms < 200 ? 'text-green-400' : ms < 1000 ? 'text-yellow-400' : 'text-orange-400'
  return (
    <span className={`font-mono text-[9px] tabular-nums ${color}`}>
      {ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Individual trace card
// ---------------------------------------------------------------------------

function TraceCard({ step, index }: { step: TraceStep; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const ruleColor = KIND_ACCENT[step.kind] ?? 'border-edge'
  const kindColor = KIND_TEXT[step.kind] ?? 'text-lo'

  return (
    <div className={`trace-rule ${ruleColor} py-1 animate-fade-in`}>
      {/* Header — always visible */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full text-left group"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-mono text-[9px] text-lo/40 w-4 text-right shrink-0">
            {index}
          </span>
          <span className={`font-mono text-[9px] font-bold uppercase tracking-wider ${kindColor}`}>
            {step.kind}
          </span>
          <span className="text-lo/30 text-[9px]">·</span>
          <span className="font-mono text-[9px] text-mid">{step.actor}</span>
          {step.model && (
            <>
              <span className="text-lo/30 text-[9px]">·</span>
              <span className="font-mono text-[9px] text-lo/70">{step.model}</span>
            </>
          )}
          <span className="ml-auto">
            <LatencyBadge ms={step.latency_ms} />
          </span>
        </div>
      </button>

      {/* Body — rationale always visible */}
      <p className="font-mono text-[10px] text-mid leading-relaxed mt-1 pr-1">
        {step.rationale}
      </p>

      {/* Cost */}
      {step.cost != null && step.cost > 0 && (
        <div className="mt-0.5 font-mono text-[9px] text-lo/50">
          ${step.cost.toFixed(6)} USD
        </div>
      )}

      {/* Expandable — inputs & output */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="mt-1 font-mono text-[9px] text-lo/40 hover:text-lo/70 transition-colors"
      >
        {expanded ? '▴ collapse' : '▸ inputs / output'}
      </button>

      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {Object.keys(step.inputs).length > 0 && (
            <details open className="text-[10px] font-mono">
              <summary className="text-lo/60 cursor-pointer select-none">inputs</summary>
              <pre className="mt-1 text-[9px] text-mid/80 overflow-x-auto leading-relaxed whitespace-pre-wrap break-all">
                {JSON.stringify(step.inputs, null, 2)}
              </pre>
            </details>
          )}
          {Object.keys(step.output).length > 0 && (
            <details open className="text-[10px] font-mono">
              <summary className="text-lo/60 cursor-pointer select-none">output</summary>
              <pre className="mt-1 text-[9px] text-mid/80 overflow-x-auto leading-relaxed whitespace-pre-wrap break-all">
                {JSON.stringify(step.output, null, 2)}
              </pre>
            </details>
          )}
          {step.prompt_ref && (
            <div className="font-mono text-[9px] text-lo/50">
              prompt_ref: {step.prompt_ref}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Footer — derived actors and models
// ---------------------------------------------------------------------------

function TraceFooter({ steps }: { steps: TraceStep[] }) {
  const components = [...new Set(steps.map((s) => s.actor.split('.')[0]))]
  const models = [...new Set(steps.filter((s) => s.model).map((s) => s.model!))]
  const totalCost = steps.reduce((a, s) => a + (s.cost ?? 0), 0)
  const totalMs = steps.reduce((a, s) => a + s.latency_ms, 0)

  return (
    <div className="mt-4 pt-3 border-t border-edge space-y-2">
      <div>
        <div className="font-mono text-[9px] uppercase tracking-widest text-lo/60 mb-1">
          Stack
        </div>
        <div className="flex flex-wrap gap-1">
          {['Python', 'FastAPI', 'PostgreSQL', 'SQLAlchemy', 'Next.js', 'Box HTTP'].map((s) => (
            <span key={s} className="tag">{s}</span>
          ))}
        </div>
      </div>

      <div>
        <div className="font-mono text-[9px] uppercase tracking-widest text-lo/60 mb-1">
          Data sources
        </div>
        <div className="flex flex-wrap gap-1">
          {['OpenAI', 'ElevenLabs Conversational AI', 'Jokebox archive'].map((s) => (
            <span key={s} className="tag-accent">{s}</span>
          ))}
        </div>
      </div>

      <div>
        <div className="font-mono text-[9px] uppercase tracking-widest text-lo/60 mb-1">
          Components
        </div>
        <div className="flex flex-wrap gap-1">
          {components.map((c) => (
            <span key={c} className="tag">{c}</span>
          ))}
        </div>
      </div>

      {models.length > 0 && (
        <div>
          <div className="font-mono text-[9px] uppercase tracking-widest text-lo/60 mb-1">
            Models
          </div>
          <div className="flex flex-wrap gap-1">
            {models.map((m) => (
              <span key={m} className="tag-accent">{m}</span>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center gap-4 font-mono text-[9px] text-lo/50">
        {totalCost > 0 && <span>Total cost: ${totalCost.toFixed(5)}</span>}
        <span>Wall time: {totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}</span>
        <span>{steps.length} step{steps.length !== 1 ? 's' : ''}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function Trace({ jokeId }: { jokeId: string | null }) {
  const { data: trace, isLoading, isError, error } = useQuery({
    queryKey: ['trace', jokeId],
    queryFn: async () => {
      const data = await fetchTrace(jokeId!)
      console.debug('[trace] GET /jokes/%s/trace', jokeId, data)
      return data
    },
    enabled: jokeId !== null,
    staleTime: 60_000,
  })

  if (!jokeId) {
    return (
      <div className="p-4 font-mono text-[10px] text-lo/40 text-center mt-6">
        No joke selected
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="p-4 space-y-3 animate-pulse">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 rounded bg-raised" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-4 font-mono text-[10px] text-violation/70">
        Failed to load trace{error instanceof Error ? `: ${error.message}` : '.'}
      </div>
    )
  }

  if (!trace) {
    return (
      <div className="p-4 font-mono text-[10px] text-violation/70">
        Failed to load trace.
      </div>
    )
  }

  if (trace.steps.length === 0) {
    return (
      <div className="p-4 font-mono text-[10px] text-lo/70 leading-relaxed mt-4">
        No decision steps were recorded for this joke. Seed and curated rows
        filed without <span className="text-mid">record_step</span> have no
        trail. Live generations after filing should appear here; if they do
        not, the step was never traced.
      </div>
    )
  }

  return (
    <div className="p-4 pb-8">
      <div className="section-label mb-3">
        Decision trace — {trace.steps.length} step{trace.steps.length !== 1 ? 's' : ''}
      </div>
      <div className="space-y-3">
        {trace.steps.map((step, i) => (
          <TraceCard key={step.id} step={step} index={i + 1} />
        ))}
      </div>
      <TraceFooter steps={trace.steps} />
    </div>
  )
}
