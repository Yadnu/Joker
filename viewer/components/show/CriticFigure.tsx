'use client'

/**
 * CriticFigure — Marcus Trent, the Librarian.
 * Seated at his desk, clipboard always out.
 * Pen taps at idle; writes when a card arrives.
 * One frame of eyebrow or head-shake on score reaction.
 */

import { useState, useEffect } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

interface Props {
  isWriting: boolean
  scoreReaction: 'high' | 'low' | null
  isSessionActive: boolean
}

// Cool clinical palette — right-column contrast to the warm stage.
const CC = {
  skin:       '#a89d86',
  skinDark:   '#8a8272',
  hair:       '#1a1814',
  jacket:     '#1a1e28',
  jacketDark: '#111420',
  shirt:      '#e4dfd4',
  glasses:    '#6b6050',
  desk:       '#1a1810',
  deskFront:  '#141210',
  clipboard:  '#e8e0cc',
  clipLine:   '#c8bfaa',
  pen:        '#f59e0b',
  penDark:    '#c47c08',
} as const

const headVariants = {
  normal: { rotate: 0, x: 0 },
  shake:  {
    rotate: [-2, 2, -2, 2, -1, 0],
    transition: { duration: 0.65, ease: 'easeInOut' as const },
  },
  leaning: {
    x: 4,
    transition: { duration: 0.25, ease: 'easeOut' as const },
  },
}

const penVariants = {
  tapping: {
    y: [0, -4, 0],
    transition: { duration: 1.1, repeat: Infinity, ease: 'easeInOut' as const },
  },
  writing: {
    x: [-6, 4, -4, 6, -3, 0],
    y: [-1, 1, -2, 1, 0],
    transition: { duration: 0.7, ease: 'easeInOut' as const },
  },
  still: { y: 0, x: 0 },
}

export default function CriticFigure({ isWriting, scoreReaction, isSessionActive }: Props) {
  const prefersReduced = useReducedMotion()
  const [rightBrowY, setRightBrowY] = useState(0)
  const [headState, setHeadState] = useState<'normal' | 'shake' | 'leaning'>('normal')

  useEffect(() => {
    if (scoreReaction === 'high') {
      setRightBrowY(-5)
      const t = setTimeout(() => setRightBrowY(0), 1400)
      return () => clearTimeout(t)
    }
    if (scoreReaction === 'low') {
      setHeadState('shake')
      const t = setTimeout(() => setHeadState('normal'), 700)
      return () => clearTimeout(t)
    }
  }, [scoreReaction])

  useEffect(() => {
    if (headState === 'shake') return
    setHeadState(isWriting ? 'leaning' : 'normal')
  }, [isWriting, headState])

  const penState = prefersReduced
    ? 'still'
    : isWriting
      ? 'writing'
      : isSessionActive
        ? 'tapping'
        : 'still'

  return (
    <div className="flex items-end justify-center select-none" aria-hidden="true">
      <svg
        viewBox="0 0 200 225"
        width="190"
        height="213"
        style={{ overflow: 'visible' }}
      >
        <defs>
          <radialGradient id="cf-skin" cx="38%" cy="32%" r="65%">
            <stop offset="0%"   stopColor="#b8ad96" />
            <stop offset="100%" stopColor="#8a8272" />
          </radialGradient>
          <filter id="cf-clip-shadow">
            <feDropShadow dx="2" dy="2" stdDeviation="2.5" floodOpacity="0.28" />
          </filter>
        </defs>

        {/* ── DESK ─────────────────────────────────────────────────────── */}
        {/* Top surface */}
        <rect x="0" y="150" width="200" height="16" rx="3" fill={CC.desk} />
        {/* Edge highlight */}
        <line x1="0" y1="150" x2="200" y2="150" stroke="#2a2520" strokeWidth="1" />
        {/* Front panel */}
        <rect x="0" y="166" width="200" height="59" fill={CC.deskFront} />

        {/* ── CLIPBOARD ────────────────────────────────────────────────── */}
        {/* Drop shadow */}
        <rect
          x="112" y="100"
          width="70" height="58"
          rx="4"
          fill="rgba(0,0,0,0.3)"
          transform="translate(2,3)"
          filter="url(#cf-clip-shadow)"
        />
        {/* Body */}
        <rect x="112" y="100" width="70" height="58" rx="4" fill={CC.clipboard} />
        {/* Clip */}
        <rect x="132" y="95" width="30" height="11" rx="4" fill={CC.glasses} />
        {/* Ruled lines */}
        {[0, 1, 2, 3, 4].map(i => (
          <line
            key={i}
            x1="120" y1={114 + i * 9}
            x2="174" y2={114 + i * 9}
            stroke={CC.clipLine}
            strokeWidth="0.9"
          />
        ))}
        {/* Current-line indicator — dark when writing */}
        <motion.line
          x1="120" y1="114"
          x2="174" y2="114"
          stroke={CC.glasses}
          strokeWidth="1.2"
          animate={{ opacity: isWriting ? 0.8 : 0.2 }}
          transition={{ duration: 0.3 }}
        />

        {/* ── PEN ──────────────────────────────────────────────────────── */}
        <motion.g
          variants={penVariants}
          animate={penState}
          style={{ transformOrigin: '148px 138px' }}
        >
          {/* Barrel */}
          <rect
            x="142" y="114" width="8" height="44" rx="4"
            fill={CC.pen}
            transform="rotate(-12, 146, 136)"
          />
          {/* Grip section */}
          <rect
            x="142" y="138" width="8" height="14" rx="2"
            fill={CC.penDark}
            transform="rotate(-12, 146, 145)"
          />
          {/* Tip */}
          <path
            d="M141 148 L146 163 L151 148 Z"
            fill="#1a1410"
            transform="rotate(-12, 146, 155)"
          />
          {/* Clip */}
          <rect
            x="144" y="116" width="2" height="28" rx="1"
            fill={CC.penDark}
            transform="rotate(-12, 145, 130)"
          />
        </motion.g>

        {/* ── FIGURE (upper body, desk hides lower) ────────────────────── */}

        {/* JACKET */}
        <path d="M50 102 L114 102 L118 152 L46 152 Z" fill={CC.jacket} />
        {/* Shading */}
        <path d="M50 102 L114 102 L115 122 L49 122 Z" fill={CC.jacketDark} opacity="0.55" />

        {/* LEFT LAPEL */}
        <path d="M60 102 L65 120 L51 124 Z" fill={CC.jacketDark} />
        {/* RIGHT LAPEL */}
        <path d="M104 102 L99 120 L113 124 Z" fill={CC.jacketDark} />

        {/* SHIRT strip */}
        <rect x="65" y="102" width="16" height="36" fill={CC.shirt} />

        {/* RIGHT ARM — reaching toward clipboard */}
        <path
          d="M112 110 Q132 133 142 150"
          stroke={CC.jacket} strokeWidth="10" strokeLinecap="round" fill="none"
        />
        <circle cx="143" cy="152" r="5.5" fill={CC.skin} />

        {/* LEFT ARM — resting on desk */}
        <path
          d="M51 110 Q38 133 52 152"
          stroke={CC.jacket} strokeWidth="10" strokeLinecap="round" fill="none"
        />
        <circle cx="52" cy="153" r="5.5" fill={CC.skin} />

        {/* NECK */}
        <rect x="76" y="84" width="12" height="20" rx="5" fill={CC.skin} />

        {/* ── HEAD GROUP ───────────────────────────────────────────────── */}
        <motion.g
          variants={headVariants}
          animate={prefersReduced ? 'normal' : headState}
          style={{ transformOrigin: '82px 84px' }}
        >
          {/* HAIR — close-cropped professional */}
          <path
            d="M56 60 Q60 33 82 30 Q104 33 108 60 Q97 50 82 48 Q67 50 56 60 Z"
            fill={CC.hair}
          />
          {/* Side hair */}
          <path d="M56 59 Q53 67 55 76" stroke={CC.hair} strokeWidth="4.5" fill="none" strokeLinecap="round" />
          <path d="M108 59 Q111 67 109 76" stroke={CC.hair} strokeWidth="4.5" fill="none" strokeLinecap="round" />

          {/* HEAD */}
          <ellipse cx="82" cy="65" rx="26" ry="28" fill="url(#cf-skin)" />

          {/* EARS */}
          <ellipse cx="56" cy="66" rx="4.5" ry="6.5" fill={CC.skinDark} />
          <ellipse cx="108" cy="66" rx="4.5" ry="6.5" fill={CC.skinDark} />

          {/* GLASSES — Marcus Trent's most visible feature */}
          {/* Frames */}
          <rect x="63" y="57" width="18" height="14" rx="5" fill="none" stroke={CC.glasses} strokeWidth="2" />
          <rect x="83" y="57" width="18" height="14" rx="5" fill="none" stroke={CC.glasses} strokeWidth="2" />
          {/* Bridge */}
          <line x1="81" y1="64" x2="83" y2="64" stroke={CC.glasses} strokeWidth="1.8" />
          {/* Temples */}
          <line x1="63" y1="64" x2="56" y2="66" stroke={CC.glasses} strokeWidth="1.8" />
          <line x1="101" y1="64" x2="108" y2="66" stroke={CC.glasses} strokeWidth="1.8" />

          {/* EYEBROWS — left stays flat, right can raise */}
          <path d="M64 54 Q72 52 80 54" stroke={CC.hair} strokeWidth="1.6" fill="none" strokeLinecap="round" />
          <motion.path
            d="M84 54 Q92 52 100 54"
            stroke={CC.hair}
            strokeWidth="1.6"
            fill="none"
            strokeLinecap="round"
            animate={{ y: rightBrowY }}
            transition={{ duration: 0.18 }}
          />

          {/* EYES (inside glasses) */}
          <circle cx="72"  cy="64" r="2.8" fill={CC.hair} />
          <circle cx="92"  cy="64" r="2.8" fill={CC.hair} />
          {/* Gleam */}
          <circle cx="73.2" cy="62.8" r="1" fill="white" opacity="0.65" />
          <circle cx="93.2" cy="62.8" r="1" fill="white" opacity="0.65" />

          {/* NOSE */}
          <path
            d="M81 70 Q79 77 82 78 Q85 77 83 70"
            stroke="#7a7060" strokeWidth="1.1" fill="none" opacity="0.75"
          />

          {/* MOUTH — neutral analytical line, slight downward pull at corners */}
          <path d="M74 83 Q82 85 90 83" stroke="#7a7060" strokeWidth="1.2" fill="none" strokeLinecap="round" />
          <path d="M74 83 Q72 85 72 84" stroke="#7a7060" strokeWidth="1" fill="none" />
          <path d="M90 83 Q92 85 92 84" stroke="#7a7060" strokeWidth="1" fill="none" />
        </motion.g>
      </svg>
    </div>
  )
}
