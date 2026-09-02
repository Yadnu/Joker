'use client'

/**
 * CriticColumn — Marcus Trent's desk.
 * A live feed of LibrarianCards arriving in pipeline order.
 * Cool, monospaced, clinical — explicit contrast with the Stage.
 */

import { useEffect, useRef } from 'react'
import LibrarianCard from './LibrarianCard'
import CriticFigure from './CriticFigure'
import type { LibrarianCard as LibrarianCardType } from '@/lib/useShowSession'

interface Props {
  cards: LibrarianCardType[]
  isSessionActive: boolean
  isWriting: boolean
  scoreReaction: 'high' | 'low' | null
}

export default function CriticColumn({ cards, isSessionActive, isWriting, scoreReaction }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [cards.length])

  return (
    <aside
      className="w-[42%] shrink-0 flex flex-col overflow-hidden border-l border-edge"
      style={{
        background:
          'linear-gradient(180deg, rgb(var(--color-base)) 0%, rgb(var(--color-surface)/0.4) 100%)',
        boxShadow: 'inset 2px 0 12px rgba(0,0,0,0.3)',
      }}
    >
      {/* ── Critic's figure ───────────────────────────────────────────── */}
      <div
        className="shrink-0 flex flex-col items-center border-b border-edge/60 relative overflow-hidden"
        style={{
          background:
            'radial-gradient(ellipse at 50% 80%, rgba(10,14,20,0.6) 0%, transparent 70%)',
          minHeight: 200,
        }}
      >
        {/* Cool overhead light */}
        <div
          className="absolute inset-x-0 top-0 h-full pointer-events-none"
          style={{
            background:
              'radial-gradient(ellipse at 50% 0%, rgba(100,130,180,0.04) 0%, transparent 60%)',
          }}
        />

        <CriticFigure
          isWriting={isWriting}
          scoreReaction={scoreReaction}
          isSessionActive={isSessionActive}
        />

        {/* Desk nameplate */}
        <div className="absolute bottom-2 left-0 right-0 flex justify-center">
          <span
            className="font-mono text-[9px] uppercase tracking-[0.22em] text-lo/50 px-3 py-0.5"
            style={{ background: 'rgb(var(--color-base)/0.7)', borderRadius: 2 }}
          >
            Marcus Trent · Librarian
          </span>
        </div>
      </div>

      {/* ── Desk sub-header ───────────────────────────────────────────── */}
      <header
        className="shrink-0 px-4 py-2.5 border-b border-edge"
        style={{ background: 'rgb(var(--color-surface)/0.5)' }}
      >
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-lo/80">
            Evaluation log
          </span>
          {cards.length > 0 && (
            <span className="ml-auto font-mono text-[9px] text-lo/50">
              {cards.length} step{cards.length !== 1 ? 's' : ''}
            </span>
          )}
          {isWriting && (
            <span className="font-mono text-[9px] text-accent/60 animate-pulse">
              writing…
            </span>
          )}
        </div>
      </header>

      {/* ── Card feed ─────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 px-6">
            {isSessionActive ? (
              <>
                <div className="w-1.5 h-1.5 rounded-full bg-accent/30 animate-pulse" />
                <p className="font-mono text-[10px] text-lo/40 text-center leading-relaxed">
                  Pipeline steps appear here
                  <br />
                  as each one completes.
                </p>
              </>
            ) : (
              <p className="font-mono text-[10px] text-lo/30 text-center leading-relaxed">
                Start a session to see
                <br />
                the evaluation in real time.
              </p>
            )}
          </div>
        ) : (
          <div className="px-3 py-3 space-y-2">
            {cards.map(card => (
              <LibrarianCard key={card.id} card={card} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </aside>
  )
}
