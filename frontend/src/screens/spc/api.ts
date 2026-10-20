/**
 * Systematic Prediction Challenge. BRAIN has no public API for submitting a prompt, so this
 * only checks one and keeps the record. Request bodies are snake_case ONLY — camelCase keys
 * are silently dropped. Types are written here until the next codegen run adds them.
 */

import { http } from '@/api/http'

export type Level = 'error' | 'warning' | 'info'

export interface Issue {
  level: Level
  code: string
  message: string
  where: string | null
}

export interface BookStats {
  count: number
  long: number
  short: number
  gross: number
  net: number
  distinctIsins: number
  medianHorizon: number | null
}

export interface Stability {
  runs: number
  identical: boolean
  minOverlap: number
  maxConfidenceShift: number
  unstableNames: string[]
}

export interface Overlap {
  draftId: string
  name: string
  status: string
  shared: number
  overlap: number
}

export interface Report {
  ready: boolean
  issues: Issue[]
  stats: BookStats | null
  stability: Stability | null
  overlaps: Overlap[]
}

export interface Draft {
  id: string
  name: string
  model: string
  modelVersion: string
  frequency: string
  weight: number
  prompt: string
  sampleOutput: string
  status: 'draft' | 'submitted'
  createdAt: string
  updatedAt: string
  submittedAt: string | null
  names: number
}

export interface Limits {
  active: number
  maxActive: number
  today: number
  maxPerDay: number
  coverage: number
  coverageTarget: number
}

export interface Drafts {
  drafts: Draft[]
  limits: Limits
  models: string[]
  frequencies: string[]
}

/** The form's seven fields, as the backend takes them. */
export interface Form {
  name: string
  prompt: string
  model: string
  model_version: string
  frequency: string
  weight: number
  sample_output: string
}

export const spc = {
  validate: (form: Form, extraRuns: string[], draftId: string | null) =>
    http.post<Report>('/api/spc/validate', { ...form, extra_runs: extraRuns, draft_id: draftId }),
  drafts: () => http.get<Drafts>('/api/spc/drafts'),
  create: (form: Form) => http.post<Draft>('/api/spc/drafts', form),
  update: (id: string, form: Form) => http.put<Draft>(`/api/spc/drafts/${id}`, form),
  mark: (id: string, submitted: boolean) =>
    http.post<Draft>(`/api/spc/drafts/${id}/submitted`, { submitted }),
  remove: (id: string) => http.del<void>(`/api/spc/drafts/${id}`),
}
