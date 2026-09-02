'use client'

/**
 * LibrarianCard — one step from the Critic's pipeline.
 * Opens with a one-line verdict in Marcus Trent's voice, then the detail.
 * Entry animates with framer-motion. Verdict types in character by character.
 * Links to the joke in /viewer when joke_id is present.
 */

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { motion, useReducedMotion } from 'framer-motion'
import type { LibrarianCard as LibrarianCardType } from '@/lib/useShowSession'

// ── Critic voice verdicts ────────────────────────────────────────────────

function criticVerdict(kind: string, payload: Record<string, unknown>): string {
  switch (kind) {
    case 'suggestion': {
      const angles = payload.angles as Array<{ genre: string }> | undefined ?? []
      const n = angles.length
      return n === 0
        ? 'Nothing usable surfaced. Re-routing.'
        : `${n} angle${n !== 1 ? 's' : ''} found. Strongest filed first.`
    }
    case 'generation': {
      const q = payload.intended_quality as string
      return q === 'bad'
        ? 'Deliberate weak slot. Contrast baked in.'
        : 'Material acquired. Queued for delivery.'
    }
    case 'delivery': {
      const cut = payload.interrupted as boolean | undefined
      const ms  = payload.latency_ms as number | undefined
      return cut
        ? 'Cut short. Barge-in absorbed.'
        : ms != null
          ? `Delivered in ${ms}ms. Room heard it.`
          : 'Delivered. Reaction pending.'
    }
    case 'reaction':
      return 'Reaction captured. Scoring underway.'
    case 'score': {
      const s      = payload.score as number
      const anchor = payload.rubric_anchor as string | undefined ?? ''
      if (s <= 2)  return `${s}. Bombed. Room didn't follow.`
      if (s === 3) return `${s}. Bombed. Weak setup, no landing.`
      if (s <= 5)  return `${s}. Tepid. Acknowledgment, no commitment.`
      if (s <= 7)  return `${s}. ${anchor ? anchor.charAt(0).toUpperCase() + anchor.slice(1) + '.' : 'Landed.'} The beat arrived.`
      if (s <= 9)  return `${s}. ${anchor ? anchor.charAt(0).toUpperCase() + anchor.slice(1) + '.' : 'Strong.'} Room gave it back.`
      return `${s}. Killed. Filed under exceptional.`
    }
    case 'classify': {
      const category = payload.category as string | undefined
      const reused   = payload.label_reused as boolean | undefined
      return category
        ? `${reused ? 'Existing label.' : 'New label.'} Filed under ${category}.`
        : 'Classified. Taxonomy updated.'
    }
    case 'filed':
      return 'Joke filed. Record is complete.'
    default:
      return ''
  }
}

// ── Typing text component ────────────────────────────────────────────────

function TypedText({ text }: { text: string }) {
  const prefersReduced = useReducedMotion()
  const [count, setCount] = useState(() => prefersReduced ? text.length : 0)

  useEffect(() => {
    if (prefersReduced) { setCount(text.length); return }
    if (count >= text.length) return
    const t = setTimeout(() => setCount(c => c + 1), 16)
    return () => clearTimeout(t)
  }, [count, text, prefersReduced])

  return (
    <span>
      {text.slice(0, count)}
      {count < text.length && (
        <span
          className="inline-block w-px h-[0.85em] bg-current align-middle ml-px opacity-60"
          style={{ animation: 'none' }}
        />
      )}
    </span>
  )
}

// ── Per-kind accent colours ──────────────────────────────────────────────

const KIND_LABEL: Record<string, string> = {
  suggestion: 'SUGGESTION',
  generation: 'GENERATION',
  delivery:   'DELIVERY',
  reaction:   'REACTION',
  score:      'SCORE',
  classify:   'CLASSIFY',
  filed:      'FILED',
}

const KIND_ACCENT: Record<string, string> = {
  suggestion: 'border-l-edge text-lo',
  generation: 'border-l-accent/40 text-accent/70',
  delivery:   'border-l-mid/40 text-mid/50',
  reaction:   'border-l-edge text-lo',
  score:      'border-l-accent text-accent',
  classify:   'border-l-mid/60 text-mid/70',
  filed:      'border-l-accent/60 text-accent/80',
}

const SCORE_COLOR = (n: number) =>
  n <= 3 ? 'text-violation' : n <= 5 ? 'text-mid' : n <= 7 ? 'text-hi' : 'text-accent'

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2 min-w-0">
      <span className="font-mono text-[9px] text-lo shrink-0 w-16 pt-px uppercase tracking-wider">
        {label}
      </span>
      <span className="font-mono text-[10px] text-mid/80 min-w-0 break-words">{value}</span>
    </div>
  )
}

// ── Main export ──────────────────────────────────────────────────────────

export default function LibrarianCard({ card }: { card: LibrarianCardType }) {
  const { kind, actor, model, latency_ms, rationale, payload, joke_id } = card
  const accentClass  = KIND_ACCENT[kind] ?? 'border-l-edge text-lo'
  const [lClass, tClass] = accentClass.split(' ')
  const verdict = criticVerdict(kind, payload)

  const inner = (
    <div
      className={[
        'border-l-2 pl-3 py-2.5 space-y-1.5',
        'bg-base rounded-r border border-l-0 border-edge/60',
        'hover:border-edge transition-colors duration-100',
        lClass,
      ].join(' ')}
    >
      {/* Header row */}
      <div className="flex items-baseline gap-2">
        <span className={['font-mono text-[9px] font-bold tracking-widest', tClass].join(' ')}>
          {KIND_LABEL[kind] ?? kind.toUpperCase()}
        </span>
        {latency_ms > 0 && (
          <span className="font-mono text-[9px] text-lo/60 ml-auto shrink-0">
            {latency_ms}ms
          </span>
        )}
      </div>

      {/* Critic's verdict — types in on arrival */}
      {verdict && (
        <p className="font-mono text-[10px] text-mid/90 leading-snug font-medium italic">
          <TypedText text={verdict} />
        </p>
      )}

      {/* Kind-specific payload detail */}
      <CardPayload kind={kind} payload={payload} />

      {/* Rationale — same text written to trace (single source) */}
      {rationale && (
        <p className="font-mono text-[9px] text-lo/65 leading-relaxed line-clamp-3 border-t border-edge/30 pt-1.5 mt-0.5">
          {rationale}
        </p>
      )}

      {/* Footer: actor · model · trace link */}
      <div className="flex items-center gap-1.5 pt-0.5">
        <span className="font-mono text-[9px] text-lo/50">{actor}</span>
        {model && (
          <>
            <span className="text-lo/30">·</span>
            <span className="font-mono text-[9px] text-lo/50">{model}</span>
          </>
        )}
        {joke_id && (
          <span className="ml-auto font-mono text-[9px] text-accent/50 hover:text-accent/80 transition-colors">
            trace →
          </span>
        )}
      </div>
    </div>
  )

  const wrapped = joke_id ? (
    <Link
      href={`/viewer?joke=${joke_id}`}
      className="block"
      title="Open trace in Archive"
    >
      {inner}
    </Link>
  ) : (
    <div>{inner}</div>
  )

  return (
    <motion.div
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
    >
      {wrapped}
    </motion.div>
  )
}

// ── Per-kind payload display ─────────────────────────────────────────────

function CardPayload({ kind, payload }: { kind: string; payload: Record<string, unknown> }) {
  switch (kind) {
    case 'suggestion': {
      const angles = (payload.angles as Array<{ genre: string; topic: string; tone_level: number }> | undefined) ?? []
      return (
        <div className="space-y-1">
          {angles.slice(0, 3).map((a, i) => (
            <div key={i} className="flex gap-1.5 items-baseline">
              <span className="font-mono text-[9px] text-lo/50 shrink-0">{i + 1}.</span>
              <span className="font-mono text-[10px] text-mid/80">{a.genre}</span>
              <span className="font-mono text-[9px] text-lo/50">·</span>
              <span className="font-mono text-[9px] text-lo/70 truncate">{a.topic}</span>
              <span className="font-mono text-[9px] text-lo/40 shrink-0 ml-auto">tone {a.tone_level}</span>
            </div>
          ))}
          {angles.length > 3 && (
            <span className="font-mono text-[9px] text-lo/40">+{angles.length - 3} more</span>
          )}
        </div>
      )
    }

    case 'generation': {
      const p = payload
      return (
        <div className="space-y-1">
          <Field label="slot"    value={`${p.slot_name as string} (${(p.slot_idx as number) + 1})`} />
          <Field label="quality" value={
            <span className={p.intended_quality === 'bad' ? 'text-violation/80' : 'text-hi/70'}>
              {p.intended_quality as string}
            </span>
          } />
          <Field label="tone"    value={`level ${p.tone_level as number}`} />
          {!!p.prompt_ref && (
            <Field label="prompt" value={<span className="text-lo/60 text-[9px]">{p.prompt_ref as string}</span>} />
          )}
        </div>
      )
    }

    case 'delivery':
      return (
        <div className="space-y-1">
          <Field label="slot" value={(payload.slot_idx as number) + 1} />
          {!!payload.interrupted && (
            <span className="font-mono text-[9px] text-violation/80">interrupted</span>
          )}
        </div>
      )

    case 'reaction': {
      const t = payload.transcript as string | undefined
      return t ? (
        <p className="font-mono text-[10px] text-mid/70 italic line-clamp-2">"{t}"</p>
      ) : null
    }

    case 'score': {
      const score  = payload.score as number
      const anchor = payload.rubric_anchor as string
      const bombed = payload.bombed as boolean
      return (
        <div className="flex items-baseline gap-3">
          <span className={['font-mono text-2xl font-bold tabular-nums', SCORE_COLOR(score)].join(' ')}>
            {score}
            <span className="text-sm font-normal text-lo/50">/10</span>
          </span>
          <span className={['font-mono text-[10px] uppercase tracking-wider font-bold', SCORE_COLOR(score)].join(' ')}>
            {anchor}
          </span>
          {bombed && (
            <span className="font-mono text-[9px] text-violation/70 ml-auto">set adapted</span>
          )}
        </div>
      )
    }

    case 'classify': {
      const path = (payload.path as string[]) ?? []
      return (
        <div className="space-y-1">
          {path.length > 0 && (
            <Field
              label="path"
              value={
                <span className="text-mid/80">
                  {path.map((p, i) => (
                    <span key={i}>
                      {i > 0 && <span className="text-lo/40 mx-1">›</span>}
                      {p}
                    </span>
                  ))}
                </span>
              }
            />
          )}
          <Field label="category" value={payload.category as string} />
        </div>
      )
    }

    case 'filed':
      return (
        <Field
          label="path"
          value={<span className="text-accent/80 break-all">{payload.path as string}</span>}
        />
      )

    default:
      return null
  }
}
