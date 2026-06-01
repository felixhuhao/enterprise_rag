import apiClient from './client'

export interface EvalBreakdownMetric {
  count: number
  avg_score: number
  pass_rate: number
  answer_pass_rate?: number | null
  citation_hit_rate?: number | null
  p95_latency_ms?: number | null
  timeout_count?: number
  hit_eval_count?: number
  hit_at_5_rate?: number | null
  hit_at_10_rate?: number | null
}

export interface EvalSummary {
  mode?: string
  flavor?: string
  case_count?: number
  scored_count?: number
  unscored?: number
  passed?: number
  warning?: number
  failed?: number
  timeout_count?: number
  failure_categories?: Record<string, number>
  judge_cache?: {
    checked: number
    hits: number
    misses: number
    cached: number
    fresh: number
    lookup_miss: number
    errors: number
    score?: EvalJudgeCacheMetric
    lookup_only?: EvalJudgeCacheMetric
  }
  hit_at_5?: number | null
  hit_at_10?: number | null
  citation_hit_rate?: number | null
  answer_pass_rate?: number | null
  latency_p50_ms?: number | null
  latency_p95_ms?: number | null
  output_path?: string
  summary_path?: string
  baseline?: EvalBaselineInfo
  baseline_delta?: EvalBaselineDelta | null
  overall: {
    count: number
    avg_score?: number | null
    pass_rate?: number | null
    hit_eval_count?: number
    hit_at_5_rate?: number | null
    hit_at_10_rate?: number | null
    p50_latency_ms?: number | null
    p95_latency_ms?: number | null
  }
  per_breakdown?: Record<string, unknown>
  per_flavor?: Record<string, EvalBreakdownMetric>
  per_strict?: EvalBreakdownMetric | null
  low_score_cases?: Array<{ id: string; score?: number; final_score?: number; question?: string; reason?: string }>
}

export interface EvalJudgeCacheMetric {
  checked: number
  hits: number
  misses: number
  cached: number
  fresh: number
  lookup_miss: number
  errors: number
}

export interface EvalBaselineInfo {
  available: boolean
  path?: string
  accepted_at?: string
  mode?: string
  flavor?: string
  accepted_current_run?: boolean
}

export interface EvalMetricDelta {
  current?: number | null
  baseline?: number | null
  delta?: number | null
  direction?: 'higher_is_better' | 'lower_is_better' | string
}

export interface EvalBaselineDelta {
  overall?: Record<string, EvalMetricDelta>
  per_flavor?: Record<string, Record<string, EvalMetricDelta>>
}

export interface EvalStatus {
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  started_at: string
  finished_at: string
  summary: EvalSummary | null
  result_path: string
  summary_path: string
  error: string
  total?: number
  current?: number
  current_id?: string
  current_question?: string
  results_preview?: EvalCaseResult[]
  mode?: string
}

export interface EvalRunOptions {
  mode?: string
  judge?: boolean
  accept_baseline?: boolean
  case_ids?: string[]
  flavor?: string
  limit?: number
  case_timeout_sec?: number
  concurrency?: number
}

export interface EvalCaseResult {
  id: string
  question: string
  index?: number | null
  total?: number | null
  status: 'queued' | 'running' | 'passed' | 'warning' | 'failed'
  label: string
  score?: number | null
  error?: string
  failure_category?: string
  failure_categories?: string[]
  judge_cache_status?: string
  judge_cache_hit?: boolean | null
  judge_cache_usage?: string
}

export interface GoldenSetCase {
  id: string
  question: string
  quick?: boolean
  slices?: string[]
  preferred_flavor: string
  strict_evidence: boolean
  eval_type: string
  level: string
  question_type: string
  expected_documents: string[]
  expected_docs?: string[]
  expected_chunk_keys?: string[]
  expected_behavior?: string
  expected_points: string[]
  expected_answer: string
  expected_points_count: number
  min_expected_citations?: number | null
  status: string
  enabled?: boolean
}

export interface GoldenCaseUpdate {
  question: string
  preferred_flavor: string
  strict_evidence: boolean
  eval_type: string
  expected_answer: string
  expected_points: string[]
  expected_documents: string[]
  min_expected_citations: number
}

export interface GoldenSetResponse {
  path: string
  count: number
  enabled_count?: number
  cases: GoldenSetCase[]
}

export async function getEvalStatus(): Promise<EvalStatus> {
  const res = await apiClient.get('/admin/eval/status')
  return res.data
}

export async function getGoldenSet(): Promise<GoldenSetResponse> {
  const res = await apiClient.get('/admin/eval/golden-set')
  return res.data
}

export async function runEval(options: EvalRunOptions | boolean = false): Promise<{ ok: boolean; status: string }> {
  const payload = typeof options === 'boolean' ? { judge: options } : options
  const res = await apiClient.post('/admin/eval/run', payload)
  return res.data
}

export async function setGoldenCaseEnabled(
  caseId: string,
  enabled: boolean,
): Promise<{ ok: boolean; path: string; case: GoldenSetCase }> {
  const res = await apiClient.patch(`/admin/eval/golden-set/${encodeURIComponent(caseId)}/enabled`, { enabled })
  return res.data
}

export async function updateGoldenCase(
  caseId: string,
  payload: GoldenCaseUpdate,
): Promise<{ ok: boolean; path: string; case: GoldenSetCase }> {
  const res = await apiClient.patch(`/admin/eval/golden-set/${encodeURIComponent(caseId)}`, payload)
  return res.data
}
