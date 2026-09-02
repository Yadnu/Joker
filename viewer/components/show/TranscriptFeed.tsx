'use client'

/**
 * TranscriptFeed — live streaming transcript of the performance.
 * Renders turn-by-turn as the host speaks and the user responds.
 * Shows barge-in markers where the host's line was cut mid-word.
 */

import { useEffect, useRef } from 'react'
import type { TranscriptTurn, BargeInMarker } from '@/lib/useShowSession'

interface Props {
  turns: TranscriptTurn[]
  bargeIns: BargeInMarker[]
  sessionActive: boolean
}

export default function TranscriptFeed({ turns, bargeIns, sessionActive }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom as new content arrives
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [turns])

  if (!sessionActive && turns.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto px-6 py-4 flex items-center justify-center">
        <p className="font-mono text-[11px] text-lo/40 text-center leading-relaxed">
          The transcript appears here as the session runs.
          <br />
          Each line arrives as it is spoken.
        </p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 min-h-0">
      {turns.map((turn, idx) => {
        const isLastHostTurn =
          turn.speaker === 'host' &&
          idx === turns.findLastIndex(t => t.speaker === 'host')

        return (
          <div key={turn.id} className="animate-fade-in">
            {/* Speaker label */}
            <div className="flex items-center gap-2 mb-1">
              <span
                className={[
                  'font-mono text-[9px] tracking-widest uppercase',
                  turn.speaker === 'host' ? 'text-accent/70' : 'text-mid/50',
                ].join(' ')}
              >
                {turn.speaker === 'host' ? 'Eddie Voss' : 'You'}
              </span>
              {turn.cutOff && (
                <span
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono
                             bg-violation/10 text-violation/80 border border-violation/20"
                  title="Interrupted"
                >
                  ✂ cut
                </span>
              )}
            </div>

            {/* Turn text */}
            <p
              className={[
                'leading-relaxed',
                turn.speaker === 'host'
                  ? 'text-hi font-sans text-sm'
                  : 'text-mid/80 font-mono text-xs',
              ].join(' ')}
            >
              {turn.text}
              {/* Streaming cursor — shown only on the live host turn */}
              {!turn.complete && turn.speaker === 'host' && isLastHostTurn && (
                <span className="inline-block w-0.5 h-[1em] bg-accent/60 ml-0.5 align-middle animate-pulse" />
              )}
              {turn.cutOff && (
                <span className="text-violation/60 ml-1">—</span>
              )}
            </p>
          </div>
        )
      })}

      {/* Barge-in markers between turns */}
      {bargeIns.length > 0 && turns.length > 0 && (
        <div className="flex items-center gap-2 py-1 animate-fade-in">
          <div className="h-px flex-1 bg-violation/20" />
          <span className="font-mono text-[9px] text-violation/60 shrink-0">
            interrupted at {bargeIns[bargeIns.length - 1].atMs}ms
          </span>
          <div className="h-px flex-1 bg-violation/20" />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
