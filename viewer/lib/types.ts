/**
 * TypeScript mirrors of box/schema/records.py.
 * Field names are fixed and graded against the spec — do not rename,
 * pluralize, or paraphrase any name.
 */

// ---------------------------------------------------------------------------
// Shared enums
// ---------------------------------------------------------------------------

export type HumorStyle =
  | 'wordplay'
  | 'observational'
  | 'absurdist'
  | 'deadpan'
  | 'dark'
  | 'physical'
  | 'self_deprecating'
  | 'topical'

export type ThemeFlag =
  | 'mortality'
  | 'institutional_failure'
  | 'existential'
  | 'medical'
  | 'workplace'
  | 'absurdist'
  | 'self_deprecating'
  | 'topical'
  | 'failure'
  | 'cynicism'
  | 'infrastructure'
  | 'bureaucracy'

export type AgeBand = 'under_25' | '25_40' | '40_60' | 'over_60'
export type OccupationField =
  | 'tech'
  | 'healthcare'
  | 'education'
  | 'trades'
  | 'finance'
  | 'student'
  | 'retired'
  | 'other'
export type EnergyLevel = 'warm' | 'dry' | 'rowdy' | 'reserved'

// ---------------------------------------------------------------------------
// Joke sub-types (exact field names from records.py)
// ---------------------------------------------------------------------------

export interface PromptTurn {
  role: string
  content: string
}

export interface JokeMetadata {
  topic: string
  style: string
  length: string
  sensitivity_flags: HumorStyle[]
  theme_flags: ThemeFlag[]
  tone_level: number
}

export interface UserContext {
  age_band?: AgeBand
  region?: string
  occupation_field?: OccupationField
  humor_preferences: HumorStyle[]
  humor_avoid: HumorStyle[]
  energy?: EnergyLevel
  first_time?: boolean
  session_notes?: string
}

export interface Attribution {
  joker: string
  account: string
}

export interface Provenance {
  source: 'generated' | 'curated'
  model: string
  prompt: string
  selection_rationale: string
}

export interface SetId {
  set: string
  position: number
}

// ---------------------------------------------------------------------------
// Canonical joke record — ten fixed fields
// ---------------------------------------------------------------------------

export interface JokeRecord {
  id: string
  file_id: string
  account_id?: string | null
  prompt_responses: PromptTurn[]
  joke_text: string
  user_reaction: string
  score: number
  category: string
  metadata: JokeMetadata
  user_context: UserContext
  attribution: Attribution
  provenance: Provenance
  set_id: SetId
}

// ---------------------------------------------------------------------------
// Tree hierarchy (GET /box)
// ---------------------------------------------------------------------------

export interface TreeFile {
  id: string
  label: string
  joke_count: number
}

export interface TreeDrawer {
  id: string
  label: string
  files: TreeFile[]
}

export interface TreeCabinet {
  id: string
  label: string
  drawers: TreeDrawer[]
}

export interface TreeData {
  cabinets: TreeCabinet[]
}

// ---------------------------------------------------------------------------
// Compliance (GET /compliance)
// ---------------------------------------------------------------------------

export interface Violation {
  level: string
  path: string
  child_count: number
  reason: string
}

export interface ComplianceData {
  compliant: boolean
  violations: Violation[]
}

// ---------------------------------------------------------------------------
// File detail (GET /files/{id})
// ---------------------------------------------------------------------------

export interface JokeSummary {
  id: string
  score: number
}

export interface FileDetail {
  id: string
  label: string
  drawer_id: string
  jokes: JokeSummary[]
}

// ---------------------------------------------------------------------------
// Trace (GET /jokes/{id}/trace)
// ---------------------------------------------------------------------------

export interface TraceStep {
  id: string
  kind: string
  actor: string
  rationale: string
  latency_ms: number
  model?: string | null
  prompt_ref?: string | null
  inputs: Record<string, unknown>
  output: Record<string, unknown>
  cost?: number | null
}

export interface TraceData {
  joke_id: string
  steps: TraceStep[]
}

// ---------------------------------------------------------------------------
// Export (GET /export)
// ---------------------------------------------------------------------------

export interface ExportFile {
  id: string
  label: string
  jokes: JokeRecord[]
}

export interface ExportDrawer {
  id: string
  label: string
  files: ExportFile[]
}

export interface ExportCabinet {
  id: string
  label: string
  drawers: ExportDrawer[]
}

export interface ExportData {
  cabinets: ExportCabinet[]
}

// ---------------------------------------------------------------------------
// Selection context — tracks which tree path a joke was selected from
// ---------------------------------------------------------------------------

export interface SelectionPath {
  cabinet: string
  drawer: string
  file: string
}

// ---------------------------------------------------------------------------
// WebSocket event types for the live show (/ route).
// These mirror the Python event models emitted by joker/realtime.py.
// One shared vocabulary — no ad-hoc string matching on the client.
// ---------------------------------------------------------------------------

/** Fatal provider error (quota, disconnect). */
export interface ShowErrorEvent {
  type: 'error'
  message: string
}
export interface TranscriptDeltaEvent {
  type: 'transcript_delta'
  speaker: 'host' | 'user'
  delta: string
}

/** One complete turn of prompt_responses as delivered (full text). */
export interface JokeTurnEvent {
  type: 'joke_turn'
  speaker: 'host' | 'user'
  content: string
}

/** The host's line was cut mid-word by a user barge-in. */
export interface BargeInEvent {
  type: 'barge_in'
  /** Text that was being spoken when the interruption occurred. */
  cut_text: string
  /** How many milliseconds into the delivery the barge-in landed. */
  at_ms: number
}

/** Kinds of pipeline steps the Librarian reports on. */
export type LibrarianStepKind =
  | 'suggestion'
  | 'generation'
  | 'delivery'
  | 'reaction'
  | 'score'
  | 'classify'
  | 'filed'

/** One completed pipeline step — one card in the Critic's feed. */
export interface LibrarianStepEvent {
  type: 'librarian_step'
  kind: LibrarianStepKind
  actor: string
  model: string | null
  latency_ms: number
  rationale: string
  payload: Record<string, unknown>
  joke_id: string | null
}

/** Current set position — which bit is up and how many total. */
export interface SetPositionEvent {
  type: 'set_position'
  current: number
  total: number
}

export type SessionStateName = 'connected' | 'listening' | 'speaking' | 'idle'

/** Session-level state change broadcast by the server. */
export interface SessionStateEvent {
  type: 'session_state'
  state: SessionStateName
}

/**
 * Output audio amplitude from the host's TTS stream.
 * Drives the host figure's mouth animation in real time.
 */
export interface AudioAmplitudeEvent {
  type: 'audio_amplitude'
  /** Normalised RMS amplitude, 0.0 (silent) to 1.0 (peak). */
  amplitude: number
}

/** Discriminated union of all typed events the show page handles. */
export type ShowWsEvent =
  | TranscriptDeltaEvent
  | JokeTurnEvent
  | BargeInEvent
  | LibrarianStepEvent
  | SetPositionEvent
  | SessionStateEvent
  | AudioAmplitudeEvent
  | ShowErrorEvent
