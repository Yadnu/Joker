'use client'

/**
 * MicControl — the Query Slot's primary interactive element.
 * Large, centered mic button with live listening state visualization.
 */

import type { SessionStatus, SessionStateName } from '@/lib/useShowSession'

interface Props {
  status: SessionStatus
  sessionState: SessionStateName
  volumeLevel: number
  onStart: () => void
  onStop: () => void
  error: string | null
}

const STATE_LABEL: Record<SessionStateName, string> = {
  connected: 'WAITING',
  listening: 'LISTENING',
  speaking: 'PERFORMING',
  idle: 'LIVE',
}

export default function MicControl({
  status,
  sessionState,
  volumeLevel,
  onStart,
  onStop,
  error,
}: Props) {
  const isActive = status === 'active'
  const isConnecting = status === 'connecting' || status === 'disconnecting'
  const isListening = isActive && sessionState === 'listening'
  const isSpeaking = isActive && sessionState === 'speaking'

  // Scale the outer glow ring based on mic volume (0 → 1)
  const ringScale = isListening ? 1 + volumeLevel * 0.45 : 1
  const ringOpacity = isListening ? 0.25 + volumeLevel * 0.65 : 0

  return (
    <div className="flex flex-col items-center gap-6 py-8">
      {/* Mic button with volume ring */}
      <div className="relative flex items-center justify-center">
        {/* Outer volume ring — responds to mic input */}
        <div
          className="absolute rounded-full border-2 border-accent/60 transition-all duration-75"
          style={{
            width: '9rem',
            height: '9rem',
            transform: `scale(${ringScale})`,
            opacity: ringOpacity,
            boxShadow: isListening
              ? `0 0 ${24 + volumeLevel * 40}px rgba(245,158,11,${0.2 + volumeLevel * 0.4})`
              : 'none',
          }}
        />

        {/* Secondary ring for speaking state */}
        {isSpeaking && (
          <div
            className="absolute rounded-full border border-accent/30 animate-pulse"
            style={{ width: '8rem', height: '8rem' }}
          />
        )}

        {/* Main button */}
        <button
          onClick={isActive ? onStop : onStart}
          disabled={isConnecting}
          aria-label={isActive ? 'End session' : 'Start session'}
          className={[
            'relative z-10 w-28 h-28 rounded-full flex flex-col items-center justify-center',
            'transition-all duration-200 select-none',
            'border-2 focus:outline-none',
            isActive
              ? isSpeaking
                ? 'border-accent/60 bg-accent/10 shadow-accent-glow'
                : isListening
                  ? 'border-accent bg-accent/20 shadow-accent-glow'
                  : 'border-accent/40 bg-raised'
              : isConnecting
                ? 'border-edge bg-surface opacity-60 cursor-wait'
                : 'border-edge bg-surface hover:border-accent/50 hover:bg-raised cursor-pointer',
          ].join(' ')}
        >
          {/* Mic icon */}
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={isListening ? 2 : 1.5}
            className={[
              'w-10 h-10 transition-all duration-200',
              isActive
                ? isListening
                  ? 'text-accent'
                  : isSpeaking
                    ? 'text-accent/70'
                    : 'text-hi/50'
                : 'text-mid/60',
            ].join(' ')}
          >
            <path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" strokeLinecap="round" />
            <line x1="12" y1="19" x2="12" y2="22" strokeLinecap="round" />
            <line x1="8" y1="22" x2="16" y2="22" strokeLinecap="round" />
          </svg>

          {/* State label inside button */}
          <span
            className={[
              'font-mono text-[9px] tracking-widest uppercase mt-1.5 transition-colors duration-200',
              isActive
                ? isListening
                  ? 'text-accent font-bold'
                  : 'text-mid/60'
                : 'text-lo/50',
            ].join(' ')}
          >
            {isConnecting
              ? 'WAIT…'
              : isActive
                ? STATE_LABEL[sessionState]
                : 'START'}
          </span>
        </button>
      </div>

      {/* Volume bars — visible only while listening */}
      {isListening && (
        <div className="flex items-end gap-[3px] h-8">
          {Array.from({ length: 12 }).map((_, i) => {
            const threshold = i / 12
            const active = volumeLevel > threshold
            return (
              <div
                key={i}
                className="w-1 rounded-full transition-all duration-75"
                style={{
                  height: `${8 + i * 4}px`,
                  backgroundColor: active
                    ? `rgba(245,158,11,${0.5 + volumeLevel * 0.5})`
                    : 'rgba(48,41,30,1)',
                }}
              />
            )
          })}
        </div>
      )}

      {/* Error message */}
      {error && (
        <p className="font-mono text-[10px] text-violation/80 text-center max-w-[18rem] leading-relaxed">
          {error}
        </p>
      )}

      {/* Instruction hint — only when idle */}
      {status === 'idle' && !error && (
        <p className="font-mono text-[10px] text-lo/50 text-center max-w-[16rem] leading-relaxed">
          Click to start the session. Speak to hear Eddie Voss deliver a joke.
        </p>
      )}

      {/* End button — separate from main button, shown when active */}
      {isActive && (
        <button
          onClick={onStop}
          className="btn text-[10px] border-violation/30 text-violation/70 hover:border-violation/60 hover:text-violation"
        >
          End Session
        </button>
      )}
    </div>
  )
}
