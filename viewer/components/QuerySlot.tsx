'use client'

import { useState, useRef, useCallback, useEffect } from 'react'
import { getWsUrl } from '@/lib/api'
import type { SelectionPath } from '@/lib/types'

// ---------------------------------------------------------------------------
// AudioWorklet processor — runs in an AudioWorkletGlobalScope.
// Inlined as a blob to avoid needing a file in /public.
// ---------------------------------------------------------------------------

const PROCESSOR_CODE = `
class PCM16Processor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true
    const samples = input[0]
    const pcm = new Int16Array(samples.length)
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }
    this.port.postMessage(pcm.buffer, [pcm.buffer])
    return true
  }
}
registerProcessor('pcm16-processor', PCM16Processor)
`

// ---------------------------------------------------------------------------
// Status type
// ---------------------------------------------------------------------------

type SessionStatus =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'disconnecting'
  | 'done'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  onSelectJoke: (id: string, path?: SelectionPath) => void
  onConnectionChange: (connected: boolean) => void
  onSessionEnd: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QuerySlot({ onSelectJoke, onConnectionChange, onSessionEnd }: Props) {
  const [status, setStatus] = useState<SessionStatus>('idle')
  const [transcript, setTranscript] = useState<string>('')
  const [userTranscript, setUserTranscript] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  // Refs for audio and WebSocket — stable across renders
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const playTimeRef = useRef<number>(0)

  // Sync connection state to parent
  const updateStatus = useCallback(
    (s: SessionStatus) => {
      setStatus(s)
      onConnectionChange(s === 'active')
    },
    [onConnectionChange],
  )

  // ---------------------------------------------------------------------------
  // Audio playback — enqueue PCM16 chunks
  // ---------------------------------------------------------------------------

  const enqueuePCM16 = useCallback((data: ArrayBuffer) => {
    const ctx = audioCtxRef.current
    if (!ctx) return
    const int16 = new Int16Array(data)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768
    }
    const buffer = ctx.createBuffer(1, float32.length, 24000)
    buffer.copyToChannel(float32, 0)
    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.connect(ctx.destination)
    const now = ctx.currentTime
    if (playTimeRef.current < now) playTimeRef.current = now
    src.start(playTimeRef.current)
    playTimeRef.current += buffer.duration
  }, [])

  // ---------------------------------------------------------------------------
  // Stop session — tear down in reverse order
  // ---------------------------------------------------------------------------

  const stopSession = useCallback(() => {
    updateStatus('disconnecting')

    // Close mic capture
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect()
      workletNodeRef.current = null
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (audioCtxRef.current) {
      void audioCtxRef.current.close()
      audioCtxRef.current = null
    }

    // Close WebSocket
    if (wsRef.current && wsRef.current.readyState < WebSocket.CLOSING) {
      wsRef.current.close()
    }
    wsRef.current = null

    updateStatus('done')
    onSessionEnd()
  }, [updateStatus, onSessionEnd])

  // Cleanup on unmount
  useEffect(() => () => { stopSession() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Start session
  // ---------------------------------------------------------------------------

  const startSession = useCallback(async () => {
    setError(null)
    setTranscript('')
    setUserTranscript('')
    updateStatus('connecting')

    // --- Microphone ---
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    } catch {
      setError('Microphone access denied. Grant permission and try again.')
      updateStatus('idle')
      return
    }
    streamRef.current = stream

    // --- AudioContext at 24 kHz (OpenAI Realtime format) ---
    const ctx = new AudioContext({ sampleRate: 24000 })
    audioCtxRef.current = ctx
    playTimeRef.current = 0

    // Load AudioWorklet processor from blob URL
    let workletUrl: string | null = null
    try {
      const blob = new Blob([PROCESSOR_CODE], { type: 'application/javascript' })
      workletUrl = URL.createObjectURL(blob)
      await ctx.audioWorklet.addModule(workletUrl)
    } catch (err) {
      setError(`AudioWorklet failed: ${err}`)
      stream.getTracks().forEach((t) => t.stop())
      void ctx.close()
      audioCtxRef.current = null
      updateStatus('idle')
      return
    } finally {
      if (workletUrl) URL.revokeObjectURL(workletUrl)
    }

    // --- WebSocket ---
    const sessionId = `viewer-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const ws = new WebSocket(getWsUrl(sessionId))
    wsRef.current = ws
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      updateStatus('active')

      // Wire mic → PCM16 worklet → WebSocket
      const source = ctx.createMediaStreamSource(stream)
      sourceRef.current = source
      const worklet = new AudioWorkletNode(ctx, 'pcm16-processor')
      workletNodeRef.current = worklet

      worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(e.data)
        }
      }

      source.connect(worklet)
      // worklet does not need to connect to destination — we only want the port
    }

    ws.onmessage = (e: MessageEvent<ArrayBuffer | string>) => {
      if (e.data instanceof ArrayBuffer) {
        // Raw PCM16 audio from Joker TTS
        enqueuePCM16(e.data)
        return
      }

      // JSON event forwarded from OpenAI Realtime
      try {
        const event = JSON.parse(e.data as string) as Record<string, unknown>
        const etype = event.type as string | undefined

        if (etype === 'response.audio_transcript.delta') {
          setTranscript((t) => t + ((event.delta as string | undefined) ?? ''))
        }
        if (etype === 'response.audio_transcript.done') {
          setTranscript((t) => t.trim())
        }
        if (
          etype === 'conversation.item.input_audio_transcription.completed'
        ) {
          const text = (event.transcript as string | undefined) ?? ''
          setUserTranscript((t) => (t ? t + ' ' + text : text))
        }
      } catch {
        // non-JSON binary text edge case — ignore
      }
    }

    ws.onerror = () => {
      setError('WebSocket error — check that the Box server is running.')
      stopSession()
    }

    ws.onclose = () => {
      if (status !== 'disconnecting' && status !== 'done') {
        stopSession()
      }
    }
  }, [enqueuePCM16, stopSession, updateStatus, status])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isActive = status === 'active'
  const isConnecting = status === 'connecting' || status === 'disconnecting'

  return (
    <div className="shrink-0 border-b border-edge bg-surface">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 pt-2.5 pb-1">
        <span className="font-display text-xs font-bold tracking-widest uppercase text-mid/70">
          Query Slot
        </span>
        {isActive && (
          <span className="flex items-center gap-1 ml-1">
            <span className="on-air w-1.5 h-1.5 rounded-full bg-red-500 block" />
            <span className="font-mono text-[9px] text-red-400">LIVE</span>
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {isActive ? (
            <button
              onClick={stopSession}
              className="btn text-[10px] border-red-500/40 text-red-400 hover:border-red-500/70"
            >
              End Session
            </button>
          ) : (
            <button
              onClick={startSession}
              disabled={isConnecting}
              className="btn-accent text-[10px]"
            >
              {isConnecting ? 'Connecting…' : 'Start Session'}
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-3 mb-2 px-2 py-1.5 text-[10px] font-mono text-violation/90 bg-violation/10 border border-violation/30 rounded">
          {error}
        </div>
      )}

      {/* Transcript area */}
      <div className="mx-3 mb-2.5 min-h-[4rem] max-h-40 overflow-y-auto rounded border border-edge bg-base/60 p-2 space-y-1">
        {status === 'idle' && !transcript && (
          <p className="font-mono text-[10px] text-lo/40 italic">
            Start a session to speak to the Joker. The joke text and audio will appear here.
          </p>
        )}

        {userTranscript && (
          <div>
            <span className="font-mono text-[9px] text-mid/50 uppercase tracking-wider block mb-0.5">
              You
            </span>
            <p className="font-mono text-[10px] text-mid/80">{userTranscript}</p>
          </div>
        )}

        {transcript && (
          <div>
            <span className="font-mono text-[9px] text-accent/60 uppercase tracking-wider block mb-0.5">
              Joker
            </span>
            <p className="font-mono text-[10px] text-hi leading-relaxed">{transcript}</p>
          </div>
        )}

        {isActive && !transcript && (
          <p className="font-mono text-[10px] text-lo/40 animate-pulse">Listening…</p>
        )}

        {status === 'done' && (
          <p className="font-mono text-[9px] text-lo/50 border-t border-edge pt-1 mt-1">
            Session ended. New jokes may appear in the archive — browse the tree to find them.
          </p>
        )}
      </div>
    </div>
  )
}
