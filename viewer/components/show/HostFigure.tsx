'use client'

/**
 * HostFigure — Eddie Voss, host of "The Late Word with Eddie Voss."
 * Inline SVG puppet animated with framer-motion.
 * Mouth tracks host output amplitude. Reacts to barge-in and bombing.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import type { SessionStateName } from '@/lib/useShowSession'

interface Props {
  sessionState: SessionStateName
  amplitude: number        // 0–1 host output level
  wasInterrupted: boolean  // barge-in just fired
  isBombing: boolean       // latest score < 3
}

// Warm colour palette — stays on the amber/sepia side of the stage light.
const C = {
  skin:      '#c8a97a',
  skinDark:  '#a87c50',
  hair:      '#2a1a0e',
  suit:      '#221e16',
  suitMid:   '#2a2318',
  suitDark:  '#181510',
  shirt:     '#e8dcc8',
  tie:       '#f59e0b',
  tieDark:   '#c47c08',
  mic:       '#6b6050',
  micDark:   '#3a3020',
  noseShadow:'#9e7040',
} as const

// Body posture variants
const bodyVariants = {
  breathing: {
    y: [0, -2, 0],
    transition: { duration: 3.5, repeat: Infinity, ease: 'easeInOut' as const, repeatType: 'mirror' as const },
  },
  cut: {
    y: 12,
    rotate: -3,
    transition: { duration: 0.07, ease: 'easeOut' as const },
  },
  bomb: {
    y: 5,
    scale: 0.97,
    transition: { duration: 0.18, ease: 'easeOut' as const },
  },
  still: { y: 0, rotate: 0, scale: 1 },
}

const headVariants = {
  normal: { rotate: 0, x: 0 },
  cut:    { rotate: -5, x: -5, transition: { duration: 0.09 } },
  bomb:   { rotate: 3,  x: 0,  transition: { duration: 0.25 } },
}

export default function HostFigure({ sessionState, amplitude, wasInterrupted, isBombing }: Props) {
  const prefersReduced = useReducedMotion()
  const [isBlinking, setIsBlinking] = useState(false)
  const [posture, setPosture] = useState<'breathing' | 'cut' | 'bomb' | 'still'>('still')
  const blinkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Scheduled random blinking
  const scheduleBlink = useCallback(() => {
    const delay = 2600 + Math.random() * 3800
    blinkTimerRef.current = setTimeout(() => {
      if (prefersReduced) { scheduleBlink(); return }
      setIsBlinking(true)
      setTimeout(() => { setIsBlinking(false); scheduleBlink() }, 110)
    }, delay)
  }, [prefersReduced])

  useEffect(() => {
    setPosture(prefersReduced ? 'still' : 'breathing')
    scheduleBlink()
    return () => { if (blinkTimerRef.current) clearTimeout(blinkTimerRef.current) }
  }, [scheduleBlink, prefersReduced])

  // Barge-in reaction
  useEffect(() => {
    if (!wasInterrupted) return
    setPosture('cut')
    const t = setTimeout(() => setPosture(prefersReduced ? 'still' : 'breathing'), 850)
    return () => clearTimeout(t)
  }, [wasInterrupted, prefersReduced])

  // Bombing reaction
  useEffect(() => {
    if (!isBombing) return
    setPosture('bomb')
    const t = setTimeout(() => setPosture(prefersReduced ? 'still' : 'breathing'), 1800)
    return () => clearTimeout(t)
  }, [isBombing, prefersReduced])

  const isSpeaking = sessionState === 'speaking'
  const mouthOpen  = isSpeaking ? Math.max(0.08, amplitude) : 0.04
  const lidScale   = isBlinking ? 1 : 0
  const headState  = posture === 'cut' ? 'cut' : posture === 'bomb' ? 'bomb' : 'normal'

  return (
    <div className="flex items-center justify-center select-none" aria-hidden="true">
      <motion.svg
        viewBox="0 0 160 278"
        width="148"
        height="257"
        style={{ overflow: 'visible' }}
      >
        <defs>
          <radialGradient id="hf-spot" cx="50%" cy="95%" r="65%">
            <stop offset="0%"   stopColor="rgba(245,158,11,0.22)" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
          <radialGradient id="hf-skin" cx="38%" cy="32%" r="68%">
            <stop offset="0%"   stopColor="#d4a870" />
            <stop offset="100%" stopColor="#b8925a" />
          </radialGradient>
        </defs>

        {/* Stage floor glow */}
        <ellipse cx="80" cy="272" rx="70" ry="16" fill="url(#hf-spot)" />
        {/* Foot shadow */}
        <ellipse cx="84" cy="263" rx="32" ry="7" fill="rgba(0,0,0,0.38)" />

        {/* ── MIC STAND (static, never animated) ───────────────────────── */}
        <g opacity="0.92">
          {/* Base */}
          <rect x="30" y="263" width="38" height="5" rx="2.5" fill={C.micDark} />
          {/* Vertical pole */}
          <rect x="47" y="136" width="3"  height="128" rx="1.5" fill={C.mic} />
          {/* Boom arm */}
          <line x1="48" y1="142" x2="40" y2="122" stroke={C.mic} strokeWidth="2.5" strokeLinecap="round" />
          {/* Capsule body */}
          <rect x="32" y="108" width="16" height="30" rx="8" fill={C.mic} />
          {/* Grille lines */}
          {[0, 1, 2, 3].map(i => (
            <line
              key={i}
              x1="33" y1={115 + i * 5}
              x2="47" y2={115 + i * 5}
              stroke={C.micDark}
              strokeWidth="0.9"
              opacity="0.65"
            />
          ))}
          {/* Mic holder ring */}
          <circle cx="40" cy="121" r="4.5" fill="none" stroke={C.micDark} strokeWidth="2" />
        </g>

        {/* ── MAIN BODY GROUP (breathing / cut / bomb) ──────────────────── */}
        <motion.g
          variants={bodyVariants}
          animate={posture}
          style={{ transformOrigin: '88px 200px' }}
        >
          {/* LEGS */}
          <rect x="67" y="186" width="14" height="62" rx="2" fill={C.suitDark} />
          <rect x="86" y="186" width="14" height="62" rx="2" fill={C.suitDark} />

          {/* SHOES */}
          <ellipse cx="74" cy="252" rx="14" ry="5.5" fill="#0f0d0a" />
          <ellipse cx="93" cy="252" rx="14" ry="5.5" fill="#0f0d0a" />
          {/* Shoe gleam */}
          <ellipse cx="70" cy="248" rx="5"  ry="2"   fill="#221e16" opacity="0.55" />
          <ellipse cx="90" cy="248" rx="5"  ry="2"   fill="#221e16" opacity="0.55" />

          {/* LEFT ARM — reaches toward mic */}
          <path
            d="M58 112 Q43 142 47 168"
            stroke={C.suit} strokeWidth="11" strokeLinecap="round" fill="none"
          />
          <circle cx="46" cy="170" r="6" fill={C.skin} />

          {/* RIGHT ARM — hangs naturally */}
          <path
            d="M118 112 Q130 140 124 168"
            stroke={C.suit} strokeWidth="11" strokeLinecap="round" fill="none"
          />
          <circle cx="123" cy="170" r="6" fill={C.skin} />

          {/* JACKET */}
          <path d="M55 104 L121 104 L126 186 L50 186 Z" fill={C.suit} />
          {/* Jacket shading */}
          <path d="M55 104 L121 104 L122 128 L54 128 Z" fill={C.suitMid} opacity="0.55" />

          {/* LEFT LAPEL */}
          <path d="M67 104 L73 128 L58 132 Z" fill={C.suitDark} />
          {/* RIGHT LAPEL */}
          <path d="M109 104 L103 128 L118 132 Z" fill={C.suitDark} />

          {/* SHIRT strip */}
          <rect x="73" y="104" width="20" height="46" fill={C.shirt} />

          {/* TIE */}
          <path d="M79 106 L87 106 L85 142 L83 145 L81 142 Z" fill={C.tie} />
          {/* Tie knot */}
          <ellipse cx="83" cy="107" rx="5" ry="3.5" fill={C.tieDark} />

          {/* NECK */}
          <rect x="77" y="87" width="13" height="19" rx="5" fill={C.skin} />

          {/* ── HEAD GROUP (tilt on cut / bomb) ─────────────────────────── */}
          <motion.g
            variants={headVariants}
            animate={headState}
            style={{ transformOrigin: '83px 87px' }}
          >
            {/* HAIR */}
            <path
              d="M56 63 Q60 32 83 28 Q108 32 112 63 Q100 50 83 48 Q66 50 56 63 Z"
              fill={C.hair}
            />
            {/* Side hair / sideburns */}
            <path d="M56 61 Q53 70 55 80" stroke={C.hair} strokeWidth="5.5" fill="none" strokeLinecap="round" />
            <path d="M112 61 Q115 70 113 80" stroke={C.hair} strokeWidth="5.5" fill="none" strokeLinecap="round" />

            {/* HEAD */}
            <ellipse cx="83" cy="63" rx="28" ry="30" fill="url(#hf-skin)" />

            {/* EARS */}
            <ellipse cx="55" cy="64" rx="5"   ry="7.5" fill={C.skinDark} />
            <ellipse cx="111" cy="64" rx="5"  ry="7.5" fill={C.skinDark} />

            {/* EYEBROWS */}
            <path d="M68 52 Q75 50 78 53" stroke={C.hair} strokeWidth="1.9" fill="none" strokeLinecap="round" />
            <path d="M88 53 Q91 50 98 52" stroke={C.hair} strokeWidth="1.9" fill="none" strokeLinecap="round" />

            {/* EYE WHITES */}
            <ellipse cx="73" cy="59" rx="6.5" ry="5.5" fill="white" />
            <ellipse cx="93" cy="59" rx="6.5" ry="5.5" fill="white" />

            {/* PUPILS */}
            <circle cx="74"  cy="59.5" r="3.5" fill={C.hair} />
            <circle cx="94"  cy="59.5" r="3.5" fill={C.hair} />
            {/* Gleam */}
            <circle cx="75.5" cy="57.8" r="1.3" fill="white" opacity="0.85" />
            <circle cx="95.5" cy="57.8" r="1.3" fill="white" opacity="0.85" />

            {/* EYELIDS (blink) — scaleY 0 = open, 1 = closed */}
            <motion.rect
              x={67} y={54}
              width={13} height={11}
              rx={3}
              fill={C.skin}
              animate={{ scaleY: lidScale }}
              style={{ transformBox: 'fill-box', transformOrigin: 'top' }}
              transition={{ duration: 0.07 }}
            />
            <motion.rect
              x={87} y={54}
              width={13} height={11}
              rx={3}
              fill={C.skin}
              animate={{ scaleY: lidScale }}
              style={{ transformBox: 'fill-box', transformOrigin: 'top' }}
              transition={{ duration: 0.07 }}
            />

            {/* NOSE */}
            <path
              d="M82 67 Q79 76 83 78 Q87 76 84 67"
              stroke={C.noseShadow} strokeWidth="1.3" fill="none" opacity="0.8"
            />

            {/* MOUTH — animated by amplitude */}
            {/* Ellipse for open mouth */}
            <motion.ellipse
              cx={83} cy={80}
              rx={7}
              animate={{ ry: mouthOpen * 7, opacity: isSpeaking ? 1 : 0.7 }}
              transition={{ duration: 0.045 }}
              fill={C.hair}
              style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
            />
            {/* Neutral lip line (more visible when silent) */}
            <motion.path
              d="M76 79 Q83 82 90 79"
              stroke={C.noseShadow}
              strokeWidth="1.2"
              fill="none"
              strokeLinecap="round"
              animate={{ opacity: isSpeaking && amplitude > 0.15 ? 0.2 : 0.85 }}
              transition={{ duration: 0.08 }}
            />
          </motion.g>
        </motion.g>
      </motion.svg>
    </div>
  )
}
