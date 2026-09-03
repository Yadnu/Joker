'use client'

/**
 * useShowSession — manages the full-duplex WebSocket + audio pipeline for the
 * live show page (/ route).
 *
 * Handles:
 *   • Microphone capture → PCM16 → WebSocket
 *   • PCM16 audio playback from the server (host TTS)
 *   • Mic volume metering for the listening animation
 *   • Typed event parsing for all custom events the server emits
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import { getWsUrl } from '@/lib/api'
import type {
  ShowWsEvent,
  LibrarianStepKind,
  SessionStateName,
} from '@/lib/types'

// Re-export so consumers can import SessionStateName from this module.
export type { SessionStateName }

// ---------------------------------------------------------------------------
// AudioWorklet processor — inlined as blob to avoid needing a public/ file.
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
// Types
// ---------------------------------------------------------------------------

export type SessionStatus = 'idle' | 'connecting' | 'active' | 'disconnecting' | 'done'

export interface TranscriptTurn {
  id: string
  speaker: 'host' | 'user'
  /** Accumulated text for this turn. May be incomplete while streaming. */
  text: string
  /** False while the host is still speaking (streaming deltas). */
  complete: boolean
  /** Host line was cut at this position by a barge-in. */
  cutOff?: boolean
}

export interface BargeInMarker {
  id: string
  cutText: string
  atMs: number
}

export interface LibrarianCard {
  id: string
  kind: LibrarianStepKind
  actor: string
  model: string | null
  latency_ms: number
  rationale: string
  payload: Record<string, unknown>
  joke_id: string | null
  arrivedAt: number
  trigger_type?: string | null
  trigger_text?: string | null
  turn_id?: string | null
  turn_index?: number | null
}

export interface SetPosition {
  current: number
  total: number
}

export interface ShowSessionResult {
  status: SessionStatus
  sessionState: SessionStateName
  transcriptTurns: TranscriptTurn[]
  bargeIns: BargeInMarker[]
  librarianCards: LibrarianCard[]
  setPosition: SetPosition | null
  /** Microphone input level (0–1) — drives listening animation. */
  volumeLevel: number
  /** Host output amplitude (0–1) — drives mouth/speech animation. */
  hostAmplitude: number
  error: string | null
  startSession: () => Promise<void>
  stopSession: () => void
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useShowSession(opts?: { onSessionEnd?: () => void }): ShowSessionResult {
  const [status, setStatus] = useState<SessionStatus>('idle')
  const [sessionState, setSessionState] = useState<SessionStateName>('idle')
  const [transcriptTurns, setTranscriptTurns] = useState<TranscriptTurn[]>([])
  const [bargeIns, setBargeIns] = useState<BargeInMarker[]>([])
  const [librarianCards, setLibrarianCards] = useState<LibrarianCard[]>([])
  const [setPosition, setSetPosition] = useState<SetPosition | null>(null)
  const [volumeLevel, setVolumeLevel] = useState(0)
  const [hostAmplitude, setHostAmplitude] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const playTimeRef = useRef<number>(0)
  const volRafRef = useRef<number | null>(null)
  const statusRef = useRef<SessionStatus>('idle')
  const amplitudeDecayRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const updateStatus = useCallback((s: SessionStatus) => {
    setStatus(s)
    statusRef.current = s
  }, [])

  // -------------------------------------------------------------------------
  // Audio playback — enqueue PCM16 chunks for seamless playback
  // -------------------------------------------------------------------------

    const enqueuePCM16 = useCallback((data: ArrayBuffer) => {
    const ctx = audioCtxRef.current
    if (!ctx) return
    if (ctx.state === 'suspended') void ctx.resume()
    const int16 = new Int16Array(data)
    const float32 = new Float32Array(int16.length)
    let sumSq = 0
    for (let i = 0; i < int16.length; i++) {
      const s = Math.max(-1, Math.min(1, int16[i] / 32768))
      float32[i] = s
      sumSq += s * s
    }
    // RMS amplitude → drives host figure mouth animation
    const rms = Math.sqrt(sumSq / int16.length)
    setHostAmplitude(Math.min(1, rms * 6))
    if (amplitudeDecayRef.current) clearTimeout(amplitudeDecayRef.current)
    amplitudeDecayRef.current = setTimeout(() => setHostAmplitude(0), 200)

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

  // -------------------------------------------------------------------------
  // Volume metering — runs as a rAF loop while the session is active
  // -------------------------------------------------------------------------

  const startVolumeMeter = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser) return
    const dataArray = new Uint8Array(analyser.frequencyBinCount)

    const tick = () => {
      analyser.getByteFrequencyData(dataArray)
      const sum = dataArray.reduce((a, b) => a + b, 0)
      setVolumeLevel(sum / (dataArray.length * 255))
      volRafRef.current = requestAnimationFrame(tick)
    }
    volRafRef.current = requestAnimationFrame(tick)
  }, [])

  const stopVolumeMeter = useCallback(() => {
    if (volRafRef.current !== null) {
      cancelAnimationFrame(volRafRef.current)
      volRafRef.current = null
    }
    setVolumeLevel(0)
  }, [])

  // -------------------------------------------------------------------------
  // Tear down — reverse order, safe to call multiple times
  // -------------------------------------------------------------------------

  const stopSession = useCallback(() => {
    updateStatus('disconnecting')
    stopVolumeMeter()

    if (amplitudeDecayRef.current) { clearTimeout(amplitudeDecayRef.current); amplitudeDecayRef.current = null }
    setHostAmplitude(0)

    if (workletNodeRef.current) { workletNodeRef.current.disconnect(); workletNodeRef.current = null }
    if (sourceRef.current) { sourceRef.current.disconnect(); sourceRef.current = null }
    if (analyserRef.current) { analyserRef.current.disconnect(); analyserRef.current = null }
    if (streamRef.current) { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null }
    if (audioCtxRef.current) { void audioCtxRef.current.close(); audioCtxRef.current = null }
    if (wsRef.current && wsRef.current.readyState < WebSocket.CLOSING) wsRef.current.close()
    wsRef.current = null

    updateStatus('done')
    opts?.onSessionEnd?.()
  }, [updateStatus, stopVolumeMeter, opts])

  useEffect(() => () => { stopSession() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // -------------------------------------------------------------------------
  // Event parsing — routes server events to the right state updates
  // -------------------------------------------------------------------------

  const handleEvent = useCallback((event: ShowWsEvent) => {
    switch (event.type) {
      case 'session_state':
        setSessionState(event.state)
        break

      case 'transcript_delta': {
        setTranscriptTurns(prev => {
          const last = prev[prev.length - 1]
          if (last && last.speaker === event.speaker && !last.complete) {
            return prev.map((t, i) =>
              i === prev.length - 1 ? { ...t, text: t.text + event.delta } : t,
            )
          }
          return [
            ...prev,
            {
              id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
              speaker: event.speaker,
              text: event.delta,
              complete: false,
            },
          ]
        })
        break
      }

      case 'joke_turn': {
        // Mark the last open turn complete. Prefer the server's final text,
        // but fall back to accumulated delta text if the content is empty
        // (can happen if the OpenAI transcript field is absent).
        setTranscriptTurns(prev => {
          const last = prev[prev.length - 1]
          if (last && last.speaker === event.speaker && !last.complete) {
            return prev.map((t, i) =>
              i === prev.length - 1
                ? { ...t, text: event.content || t.text, complete: true }
                : t,
            )
          }
          if (!event.content) return prev
          return [
            ...prev,
            {
              id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
              speaker: event.speaker,
              text: event.content,
              complete: true,
            },
          ]
        })
        break
      }

      case 'barge_in': {
        // Mark the host's last incomplete turn as cut off.
        setTranscriptTurns(prev =>
          prev.map((t, i) =>
            i === prev.length - 1 && t.speaker === 'host' && !t.complete
              ? { ...t, complete: true, cutOff: true }
              : t,
          ),
        )
        setBargeIns(prev => [
          ...prev,
          {
            id: `barge-${Date.now()}`,
            cutText: event.cut_text,
            atMs: event.at_ms,
          },
        ])
        break
      }

      case 'librarian_step':
        setLibrarianCards(prev => [
          ...prev,
          {
            id: `card-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            kind: event.kind,
            actor: event.actor,
            model: event.model,
            latency_ms: event.latency_ms,
            rationale: event.rationale,
            payload: event.payload,
            joke_id: event.joke_id,
            arrivedAt: Date.now(),
            trigger_type: event.trigger_type ?? null,
            trigger_text: event.trigger_text ?? null,
            turn_id: event.turn_id ?? null,
            turn_index: event.turn_index ?? null,
          },
        ])
        break

      case 'set_position':
        setSetPosition({ current: event.current, total: event.total })
        break

      case 'audio_amplitude':
        setHostAmplitude(event.amplitude)
        break

      case 'error':
        setError(event.message)
        break
    }
  }, [])

  // -------------------------------------------------------------------------
  // Start session
  // -------------------------------------------------------------------------

  const startSession = useCallback(async () => {
    setError(null)
    setTranscriptTurns([])
    setBargeIns([])
    setLibrarianCards([])
    setSetPosition(null)
    setSessionState('idle')
    updateStatus('connecting')

    // Microphone
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    } catch {
      setError('Microphone access denied. Grant permission and try again.')
      updateStatus('idle')
      return
    }
    streamRef.current = stream
    const t0 = performance.now()
    const mark = (stage: string) => {
      const ms = Math.round(performance.now() - t0)
      console.log(`[timing] ${stage} +${ms}ms`)
    }
    mark('mic_permission_granted')

    // AudioContext at 24 kHz. Resume immediately so autoplay policy cannot
    // swallow the host's first utterance after the getUserMedia await.
    const ctx = new AudioContext({ sampleRate: 24000 })
    audioCtxRef.current = ctx
    playTimeRef.current = 0
    try {
      await ctx.resume()
    } catch {
      // Some browsers resume on first audio buffer instead.
    }
    mark('audio_context_resumed')

    // AudioWorklet processor for PCM16 mic capture
    let workletUrl: string | null = null
    try {
      const blob = new Blob([PROCESSOR_CODE], { type: 'application/javascript' })
      workletUrl = URL.createObjectURL(blob)
      await ctx.audioWorklet.addModule(workletUrl)
    } catch (err) {
      setError(`AudioWorklet failed: ${err}`)
      stream.getTracks().forEach(t => t.stop())
      void ctx.close()
      audioCtxRef.current = null
      updateStatus('idle')
      return
    } finally {
      if (workletUrl) URL.revokeObjectURL(workletUrl)
    }

    // WebSocket
    const sessionId = `show-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const ws = new WebSocket(getWsUrl(sessionId))
    wsRef.current = ws
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      mark('server_websocket_open')
      updateStatus('active')

      const source = ctx.createMediaStreamSource(stream)
      sourceRef.current = source

      // Analyser for volume metering
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      analyser.smoothingTimeConstant = 0.8
      analyserRef.current = analyser

      const worklet = new AudioWorkletNode(ctx, 'pcm16-processor')
      workletNodeRef.current = worklet

      worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(e.data)
      }

      // Branch: source → analyser (metering), source → worklet (capture)
      source.connect(analyser)
      source.connect(worklet)

      startVolumeMeter()
    }

    ws.onmessage = (e: MessageEvent<ArrayBuffer | string>) => {
      if (e.data instanceof ArrayBuffer) {
        if (!(enqueuePCM16 as { _first?: boolean })._first) {
          ;(enqueuePCM16 as { _first?: boolean })._first = true
          mark('first_audio_byte_received')
        }
        enqueuePCM16(e.data)
        return
      }

      try {
        const parsed = JSON.parse(e.data as string) as Record<string, unknown>
        const t = parsed.type as string | undefined
        if (!t) return

        // Handle only our typed custom events — ignore raw OpenAI events that
        // are still forwarded for backward compat with the viewer's QuerySlot.
        const customTypes = new Set([
          'transcript_delta', 'joke_turn', 'barge_in',
          'librarian_step', 'set_position', 'session_state', 'audio_amplitude',
          'error',
        ])
        if (customTypes.has(t)) {
          handleEvent(parsed as unknown as ShowWsEvent)
        }
      } catch {
        // Non-JSON or parse error — ignore
      }
    }

    ws.onerror = () => {
      setError('WebSocket error — is the Box server running?')
      stopSession()
    }

    ws.onclose = (ev: CloseEvent) => {
      console.log(`[ws] close code=${ev.code} reason=${ev.reason || '(none)'} wasClean=${ev.wasClean}`)
      if (statusRef.current !== 'disconnecting' && statusRef.current !== 'done') {
        stopSession()
      }
    }
  }, [enqueuePCM16, handleEvent, startVolumeMeter, stopSession, updateStatus])

  return {
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
  }
}
