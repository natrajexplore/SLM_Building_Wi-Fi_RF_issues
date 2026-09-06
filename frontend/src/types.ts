// Mirrors backend/schemas.py. Kept deliberately small — the canonical snapshot
// itself is sent as opaque JSON and validated server-side.

export type Band = '2.4GHz' | '5GHz' | '6GHz'
export type Confidence = 'low' | 'medium' | 'high'

export interface EvidenceItem {
  field_path: string
  observed_value: unknown
  why_it_matters: string
}

export interface RankedAlternative {
  cause_id: string
  confidence: Confidence
}

export interface Citation {
  title: string
  heading: string | null
  sources: string[]
  review_status: string
  score: number
  text: string
}

export interface RCAResult {
  cause_id: string | null
  confidence: Confidence
  evidence: EvidenceItem[]
  affected_bands: Band[]
  remediation: string[]
  data_gaps: string[]
  ranked_alternatives: RankedAlternative[]
  citations: Citation[]
}

export interface ExplainResponse {
  explanation: string
  temperature_used: number
}

export interface TaxonomyCause {
  id: string
  name: string
  bands: Band[]
  severity_default: string | null
}

export interface HealthInfo {
  status: string
  model_backend: string
  backend_ready: boolean
  backend_error: string | null
  diagnose_model: string
  diagnose_temperature: number
  explain_temperature_band: [number, number]
  rag_enabled: boolean
  rag_index: { chunks: number; embedder: string; review_status: Record<string, number> } | null
}
