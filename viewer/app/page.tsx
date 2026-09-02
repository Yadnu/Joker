'use client'

/**
 * Home page — THE SHOW.
 * Two-column live performance surface: Stage (left) + Critic's Desk (right).
 * Holds the single WebSocket connection to the Joker.
 */

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { motion, useReducedMotion } from 'framer-motion'
import { useShowSession } from '@/lib/useShowSession'
import MicControl from '@/components/show/MicControl'
import TranscriptFeed from '@/components/show/TranscriptFeed'
import CriticColumn from '@/components/show/CriticColumn'
import HostFigure from '@/components/show/HostFigure'

// ── Marquee bulb component ────────────────────────────────────────────────
function BulbRow({ count = 16 }: { count?: number }) {
  const prefersReduced = useReducedMotion()
  return (
    <div className="flex items-center justify-center gap-[10px] py-2.5 px-4" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => {
        const warm  = i % 2 === 0
        const delay = (i * 0.09) % 1.5
        return (
          <motion.div
            key={i}
            className="rounded-full shrink-0"
            style={{
              width:  warm ? 10 : 8,
              height: warm ? 10 : 8,
              background: warm
                ? 'radial-gradient(circle at 35% 35%, #fef3c7, #f59e0b)'
                : 'radial-gradient(circle at 35% 35%, #f59e0b, #78350f)',
              boxShadow: warm
                ? '0 0 8px 2px rgba(245,158,11,0.70)'
                : '0 0 4px 1px rgba(245,158,11,0.25)',
            }}
            animate={prefersReduced ? {} : {
              opacity:   warm ? [1, 0.35, 1] : [0.5, 1, 0.5],
              scale:     warm ? [1, 0.88, 1] : [0.9, 1, 0.9],
            }}
            transition={{ duration: 1.6, delay, repeat: Infinity, ease: 'easeInOut' }}
          />
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────
export default function ShowPage() {
  const session = useShowSession()

  const {
    status,
    sessionState,
    transcriptTurns,
    bargeIns,
    librarianCards,
    setPosition,
    volumeLevel,
    hostAmplitude,
    error,
    startSession,
    stopSession,
  } = session

  const isActive = status === 'active'

  // ── Derive wasInterrupted from bargeIns count change ──────────────────
  const prevBargeCountRef = useRef(0)
  const [wasInterrupted, setWasInterrupted] = useState(false)

  useEffect(() => {
    if (bargeIns.length > prevBargeCountRef.current) {
      prevBargeCountRef.current = bargeIns.length
      setWasInterrupted(true)
      const t = setTimeout(() => setWasInterrupted(false), 950)
      return () => clearTimeout(t)
    }
  }, [bargeIns.length])

  // ── Derive isBombing from most recent score card ───────────────────────
  const latestScoreCard = librarianCards.filter(c => c.kind === 'score').at(-1)
  const isBombing = latestScoreCard
    ? (latestScoreCard.payload.score as number) < 3
    : false

  // ── Critic reaction props ─────────────────────────────────────────────
  const latestScore = latestScoreCard?.payload.score as number | undefined
  const scoreReaction: 'high' | 'low' | null =
    latestScore == null ? null
    : latestScore >= 8   ? 'high'
    : latestScore <= 3   ? 'low'
    : null

  const prevCardCountRef = useRef(0)
  const [isWriting, setIsWriting] = useState(false)

  useEffect(() => {
    if (librarianCards.length > prevCardCountRef.current) {
      prevCardCountRef.current = librarianCards.length
      setIsWriting(true)
      const t = setTimeout(() => setIsWriting(false), 1400)
      return () => clearTimeout(t)
    }
  }, [librarianCards.length])

  return (
    <div
      className="flex h-screen overflow-hidden bg-base text-hi"
      style={{ isolation: 'isolate' }}
    >
      {/* ── Navigation: Archive button ─────────────────────────────────── */}
      <Link
        href="/viewer"
        className="absolute top-3 right-4 z-30 btn text-[11px] tracking-wider"
      >
        The Archive →
      </Link>

      {/* ── Left: THE STAGE ──────────────────────────────────────────────── */}
      <main
        className="flex-1 min-w-0 flex flex-col overflow-hidden"
        style={{
          background:
            'linear-gradient(180deg, rgb(var(--color-surface)) 0%, rgb(var(--color-base)) 100%)',
          boxShadow: '4px 0 24px rgba(0,0,0,0.4)',
        }}
      >
        {/* ── Marquee header ─────────────────────────────────────────── */}
        <header
          className="shrink-0 flex flex-col border-b border-edge/60"
          style={{
            background: 'linear-gradient(180deg, rgb(var(--color-raised)) 0%, rgb(var(--color-surface)) 100%)',
          }}
        >
          {/* Top bulb row */}
          <BulbRow count={18} />

          {/* Title bar */}
          <div className="flex items-start justify-between px-6 pb-3">
            <div>
              <h1
                className="font-display font-bold text-5xl tracking-[0.15em] text-hi uppercase leading-none"
                style={{ textShadow: '0 2px 18px rgba(245,158,11,0.18)' }}
              >
                Eddie Voss
              </h1>
              <p className="font-mono text-[11px] text-mid/60 tracking-widest uppercase mt-1.5">
                The Late Word with Eddie Voss
              </p>
            </div>

            {/* ON AIR + set position */}
            <div className="flex flex-col items-end gap-1.5 pt-1">
              {isActive ? (
                <div className="flex items-center gap-2">
                  <span className="on-air w-2.5 h-2.5 rounded-full bg-red-500 block shrink-0" />
                  <span className="font-display text-sm tracking-[0.2em] text-red-400 font-bold uppercase">
                    On Air
                  </span>
                </div>
              ) : (
                <div className="flex items-center gap-2 opacity-25">
                  <span className="w-2.5 h-2.5 rounded-full bg-edge block shrink-0" />
                  <span className="font-display text-sm tracking-[0.2em] text-lo uppercase">
                    Off Air
                  </span>
                </div>
              )}

              {setPosition && (
                <span className="font-mono text-[10px] text-mid/50">
                  bit {setPosition.current} of {setPosition.total}
                </span>
              )}
            </div>
          </div>

          {/* Bottom bulb row */}
          <BulbRow count={18} />
        </header>

        {/* ── HOST FIGURE — Eddie Voss ────────────────────────────────── */}
        <div
          className="shrink-0 flex items-center justify-center relative overflow-hidden"
          style={{
            minHeight: 170,
            background:
              'radial-gradient(ellipse at 50% 60%, rgba(245,158,11,0.07) 0%, transparent 68%)',
          }}
        >
          {/* Barge-in visual cut marker */}
          {wasInterrupted && (
            <motion.div
              className="absolute inset-0 flex items-center justify-center pointer-events-none"
              initial={{ opacity: 0 }}
              animate={{ opacity: [0, 1, 0] }}
              transition={{ duration: 0.5, times: [0, 0.15, 1] }}
            >
              <span
                className="font-mono text-[9px] tracking-widest text-violation/80 uppercase border border-violation/30 px-2 py-0.5 rounded"
                style={{ background: 'rgba(224,74,42,0.08)' }}
              >
                ✂ cut
              </span>
            </motion.div>
          )}

          <HostFigure
            sessionState={sessionState}
            amplitude={hostAmplitude}
            wasInterrupted={wasInterrupted}
            isBombing={isBombing}
          />
        </div>

        {/* ── THE QUERY SLOT ─────────────────────────────────────────── */}
        <div className="shrink-0 flex flex-col items-center border-y border-edge/40 relative">
          {/* Warm spotlight behind the mic */}
          <div
            className="absolute inset-x-0 top-0 h-full pointer-events-none"
            style={{
              background:
                'radial-gradient(ellipse at 50% 40%, rgba(245,158,11,0.06) 0%, transparent 65%)',
            }}
          />
          <MicControl
            status={status}
            sessionState={sessionState}
            volumeLevel={volumeLevel}
            onStart={startSession}
            onStop={stopSession}
            error={error}
          />
        </div>

        {/* ── Live transcript ─────────────────────────────────────────── */}
        <TranscriptFeed
          turns={transcriptTurns}
          bargeIns={bargeIns}
          sessionActive={isActive}
        />

        {/* Session-end notice */}
        {status === 'done' && (
          <div className="shrink-0 px-6 py-3 border-t border-edge/40">
            <p className="font-mono text-[10px] text-lo/50">
              Session ended. New jokes may have been filed.{' '}
              <Link href="/viewer" className="text-accent/60 hover:text-accent underline underline-offset-2">
                Browse the archive →
              </Link>
            </p>
          </div>
        )}
      </main>

      {/* ── Right: THE CRITIC'S DESK ─────────────────────────────────────── */}
      <CriticColumn
        cards={librarianCards}
        isSessionActive={isActive}
        isWriting={isWriting}
        scoreReaction={scoreReaction}
      />
    </div>
  )
}
