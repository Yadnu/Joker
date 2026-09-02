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
