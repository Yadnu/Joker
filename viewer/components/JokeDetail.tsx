'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchJoke } from '@/lib/api'
import type {
  JokeRecord,
  PromptTurn,
  UserContext,
  SelectionPath,
  TreeData,
} from '@/lib/types'

// ---------------------------------------------------------------------------
// Score meter
// ---------------------------------------------------------------------------

const SCORE_LABELS = ['Crickets', 'Crickets', 'Bombed', 'Flat', 'Flat', 'Mild', 'Mild', 'Solid', 'Solid', 'Killer', 'Killer']

function scoreColor(score: number): string {
  if (score <= 2) return '#e04a2a'
  if (score <= 4) return '#f97316'
  if (score <= 6) return '#eab308'
  if (score <= 8) return '#22c55e'
  return '#10b981'
}

function ScoreMeter({ score, jokeId }: { score: number; jokeId: string }) {
  const pct = (score / 10) * 100
  const label = SCORE_LABELS[score] ?? 'Unknown'
  const color = scoreColor(score)

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="data-label">Score</span>
        <span className="font-mono text-xs text-mid">
          {score}<span className="text-lo">/10</span>
          <span className="mx-1.5 text-lo">—</span>
          <span style={{ color }}>{label}</span>
        </span>
      </div>
      <div className="h-1.5 bg-raised rounded-full overflow-hidden">
        <div
          key={jokeId}
          className="h-full rounded-full score-bar"
          style={
            {
              backgroundColor: color,
              '--score-pct': `${pct}%`,
            } as React.CSSProperties
          }
        />
      </div>
      <div className="flex justify-between font-mono text-[8px] text-lo/40">
        <span>0 · Crickets</span>
        <span>5 · Mild</span>
        <span>10 · Killer</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Prompt / response exchange
// ---------------------------------------------------------------------------

function PromptExchange({ turns }: { turns: PromptTurn[] }) {
  return (
    <div className="space-y-2">
      {turns.map((turn, i) => {
        if (turn.role === 'system') {
          return (
            <div
              key={i}
              className="px-3 py-2 rounded border-l-2 border-edge/60 bg-base/60 text-xs font-mono text-lo/80 italic"
            >
              <span className="not-italic font-bold text-[9px] uppercase tracking-widest text-lo/60 block mb-1">
                System
              </span>
              {turn.content}
            </div>
          )
        }
        if (turn.role === 'user') {
          return (
            <div key={i} className="flex justify-end">
              <div className="max-w-[78%] px-3 py-2 bg-raised rounded-lg rounded-tr-sm">
                <span className="font-mono font-bold text-[9px] uppercase tracking-widest text-mid/60 block mb-1 text-right">
                  Audience
                </span>
                <p className="text-sm text-hi leading-relaxed">{turn.content}</p>
              </div>
            </div>
          )
        }
        return (
          <div key={i} className="flex justify-start">
            <div className="max-w-[78%] px-3 py-2 bg-surface border border-accent/20 rounded-lg rounded-tl-sm">
              <span className="font-mono font-bold text-[9px] uppercase tracking-widest text-accent/70 block mb-1">
                Joker
              </span>
              <p className="text-sm text-hi leading-relaxed">{turn.content}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// User context display
// ---------------------------------------------------------------------------

function CtxRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-mono text-[9px] uppercase tracking-wider text-lo w-28 shrink-0">
        {label}
      </span>
      <span className="font-mono text-xs text-mid">{value}</span>
    </div>
  )
}

function UserContextPanel({ uc }: { uc: UserContext }) {
  return (
    <div className="card-raised p-3 space-y-1">
      <CtxRow label="Age band" value={uc.age_band?.replace('_', '–')} />
      <CtxRow label="Region" value={uc.region} />
      <CtxRow label="Occupation" value={uc.occupation_field} />
      <CtxRow label="Energy" value={uc.energy} />
      <CtxRow label="First time" value={uc.first_time == null ? null : uc.first_time ? 'Yes' : 'No'} />
      <CtxRow
        label="Preferences"
        value={uc.humor_preferences.length ? uc.humor_preferences.join(', ') : null}
      />
      <CtxRow
        label="Avoid (hard)"
        value={uc.humor_avoid.length ? uc.humor_avoid.join(', ') : null}
      />
      <CtxRow label="Notes" value={uc.session_notes} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="section-label">{label}</div>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Breadcrumb
// ---------------------------------------------------------------------------

function Breadcrumb({ path, category }: { path: SelectionPath | null; category: string }) {
  const parts = path ? [path.cabinet, path.drawer, path.file] : [category]
  return (
    <div className="flex items-center gap-1 font-mono text-[10px] text-lo flex-wrap">
      <span className="text-lo/50">Archive</span>
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-1">
          <span className="text-lo/30">›</span>
          <span className={i === parts.length - 1 ? 'text-mid' : 'text-lo'}>{p}</span>
        </span>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  jokeId: string | null
  selectionPath: SelectionPath | null
  tree: TreeData | undefined
}

export default function JokeDetail({ jokeId, selectionPath, tree }: Props) {
  const { data: joke, isLoading, isError } = useQuery({
    queryKey: ['joke', jokeId],
    queryFn: () => fetchJoke(jokeId!),
    enabled: jokeId !== null,
  })

  // Resolve path from tree if selectionPath is not already set
  const resolvedPath = useMemo<SelectionPath | null>(() => {
    if (selectionPath) return selectionPath
    if (!joke || !tree) return null
    for (const cab of tree.cabinets) {
      for (const drw of cab.drawers) {
        const f = drw.files.find((f) => f.id === joke.file_id)
        if (f) return { cabinet: cab.label, drawer: drw.label, file: f.label }
      }
    }
    return null
  }, [selectionPath, joke, tree])

  // Empty state
  if (!jokeId) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
        <div className="font-display text-5xl font-bold tracking-[0.2em] text-hi/10 uppercase select-none">
          Jokebox
        </div>
        <p className="font-mono text-xs text-lo/50 leading-relaxed max-w-xs">
          Select a joke from the archive to trace every decision from prompt to punchline.
        </p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="p-6 space-y-4 max-w-3xl mx-auto animate-pulse">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-8 rounded bg-raised" />
        ))}
      </div>
    )
  }

  if (isError || !joke) {
    return (
      <div className="p-6 font-mono text-sm text-violation">
        Failed to load joke record.
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto animate-fade-in pb-16">
      {/* Breadcrumb */}
      <Breadcrumb path={resolvedPath} category={joke.category} />

      {/* Genre badge */}
      <div className="flex items-center gap-3">
        <span className="tag-accent px-3 py-1 text-xs font-display tracking-widest uppercase">
          {joke.category}
        </span>
        <span className="font-mono text-[9px] text-lo">{joke.id}</span>
      </div>

      {/* Generation dialogue */}
      <Section label="Generation Dialogue">
        <PromptExchange turns={joke.prompt_responses} />
      </Section>

      {/* The joke */}
      <Section label="Joke">
        <div className="card p-5 border-accent/20">
          <p className="text-lg leading-relaxed text-hi font-sans">{joke.joke_text}</p>
        </div>
      </Section>

      {/* Audience reaction */}
      <Section label="Audience Reaction">
        <p className="text-sm italic text-mid pl-3 border-l-2 border-edge">
          &ldquo;{joke.user_reaction}&rdquo;
        </p>
      </Section>

      {/* Score meter */}
      <Section label="Landing Score">
        <ScoreMeter score={joke.score} jokeId={joke.id} />
      </Section>

      {/* Set identity */}
      <Section label="Set">
        <div className="card-raised p-3 flex items-center gap-6 font-mono text-xs">
          <div>
            <span className="text-lo">ID — </span>
            <span className="text-mid">{joke.set_id.set}</span>
          </div>
          <div>
            <span className="text-lo">Position — </span>
            <span className="text-accent font-semibold">#{joke.set_id.position}</span>
          </div>
        </div>
      </Section>

      {/* Metadata */}
      <Section label="Metadata">
        <div className="card-raised p-3 space-y-2">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs">
            <CtxRow label="Topic" value={joke.metadata.topic} />
            <CtxRow label="Style" value={joke.metadata.style} />
            <CtxRow label="Length" value={joke.metadata.length} />
            <CtxRow label="Tone level" value={`Level ${joke.metadata.tone_level}`} />
          </div>
          {joke.metadata.sensitivity_flags.length > 0 && (
            <div className="pt-1 flex flex-wrap gap-1">
              <span className="font-mono text-[9px] uppercase tracking-wider text-lo w-28 shrink-0 pt-0.5">
                Sensitivity
              </span>
              <div className="flex flex-wrap gap-1">
                {joke.metadata.sensitivity_flags.map((f) => (
                  <span key={f} className="tag">{f}</span>
                ))}
              </div>
            </div>
          )}
          {joke.metadata.theme_flags.length > 0 && (
            <div className="pt-1 flex flex-wrap gap-1">
              <span className="font-mono text-[9px] uppercase tracking-wider text-lo w-28 shrink-0 pt-0.5">
                Themes
              </span>
              <div className="flex flex-wrap gap-1">
                {joke.metadata.theme_flags.map((f) => (
                  <span key={f} className="tag">{f}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </Section>

      {/* Audience context */}
      <Section label="Audience Context">
        <UserContextPanel uc={joke.user_context} />
      </Section>

      {/* Attribution */}
      <Section label="Attribution">
        <div className="card-raised p-3 flex gap-8 font-mono text-xs">
          <CtxRow label="Joker" value={joke.attribution.joker} />
          <CtxRow label="Account" value={joke.attribution.account} />
        </div>
      </Section>

      {/* Provenance */}
      <Section label="Provenance">
        <div className="card-raised p-3 space-y-1.5">
          <CtxRow label="Source" value={joke.provenance.source} />
          <CtxRow label="Model" value={joke.provenance.model} />
          <CtxRow label="Prompt" value={joke.provenance.prompt} />
          <div className="mt-2 pt-2 border-t border-edge">
            <span className="font-mono text-[9px] uppercase tracking-wider text-lo block mb-1">
              Selection Rationale
            </span>
            <p className="font-mono text-xs text-mid leading-relaxed">
              {joke.provenance.selection_rationale}
            </p>
          </div>
        </div>
      </Section>
    </div>
  )
}
