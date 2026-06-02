/**
 * Query stats API
 */
import apiClient from './client'

export interface QueryStats {
  total_queries: number
  success_count: number
  total_failed: number
  failure_rate: number
  avg_rerank_score: number
  avg_result_count: number
  p95_ms: number
  fallback_count: number
  fallback_ratio: number
  avg_groundedness_score?: number | null
  low_groundedness_count?: number
}

export interface QueryStatsTrend {
  dates: string[]
  avg_rerank: number[]
  avg_result_count: number[]
  counts: number[]
  failed_counts: number[]
}

export interface RetrievedChunkItem {
  chunk_id?: number | null
  chunk_key?: string
  rank: number
  score: number
  document_id?: string
  file_title?: string
  entity_name?: string
  section_title?: string
  page?: number | null
  table_id?: string
  source_type?: string
  keywords?: string[]
  structured_tags?: string[]
  retrieval_path?: string
  stage?: string
  content_preview?: string
}

export interface SlowestStage {
  key?: string
  ms?: number
}

export interface QueryObservability {
  endpoint?: string
  timings_ms?: Record<string, number>
  resolved_settings?: Record<string, unknown>
  result_shape?: Record<string, unknown>
  fallback_info?: Record<string, unknown>
  token_usage?: Record<string, unknown>
}

export interface LatencyMetric {
  count: number
  p50_ms: number
  p95_ms: number
}

export interface QueryLatencyBreakdown {
  by_flavor: Record<string, LatencyMetric>
  by_status: Record<string, LatencyMetric>
  by_endpoint: Record<string, LatencyMetric>
  stages: Record<string, LatencyMetric>
}

export interface FlavorMetric {
  count: number
  success_count: number
  failed_count: number
  success_rate: number
  avg_rerank: number
  avg_results: number
  p95_ms: number
  fallback_count: number
  fallback_ratio: number
}

export type QueryStatsByFlavor = Record<'balanced' | 'exact' | 'recall' | 'discovery', FlavorMetric>
export type QueryStatsByStrict = Record<'non_strict' | 'strict', FlavorMetric>

export interface QueryStatsRecord {
  id: number
  session_id: string
  query: string
  search_mode: string
  search_mode_hyde: string
  result_count: number
  rerank_avg_score: number
  rerank_top_score: number
  retrieval_wall_ms: number
  first_token_ms: number
  generate_ms: number
  total_ms: number
  status: string
  error_code: string
  retrieved_chunks?: string
  citations?: string
  retrieval_flavor: string
  strict_evidence: number
  fallback_used: number
  groundedness_score?: number | null
  endpoint?: string
  timings_json?: string
  settings_json?: string
  result_shape_json?: string
  fallback_json?: string
  token_usage_json?: string
  timings?: Record<string, number>
  resolved_settings?: Record<string, unknown>
  result_shape?: Record<string, unknown>
  fallback_details?: Record<string, unknown>
  token_usage?: Record<string, unknown>
  slowest_stage?: SlowestStage
  model?: string
  total_tokens?: number | null
  user_id: string
  created_at: string
}

export interface QueryStatsRecordDetail extends QueryStatsRecord {
  retrieved_chunks_list?: RetrievedChunkItem[]
  citations_list?: Record<string, unknown>[]
  observability?: QueryObservability
}

function userParams(filterUserId: string = ''): Record<string, string> {
  return filterUserId ? { filter_user_id: filterUserId } : {}
}

export async function getQueryStats(filterUserId: string = ''): Promise<QueryStats> {
  const res = await apiClient.get('/query/stats', { params: userParams(filterUserId) })
  return res.data
}

export async function getQueryStatsTrend(filterUserId: string = ''): Promise<QueryStatsTrend> {
  const res = await apiClient.get('/query/stats/trend', { params: userParams(filterUserId) })
  return res.data
}

export async function getQueryStatsByFlavor(filterUserId: string = ''): Promise<QueryStatsByFlavor> {
  const res = await apiClient.get('/query/stats/by-flavor', { params: userParams(filterUserId) })
  return res.data
}

export async function getQueryStatsByStrict(filterUserId: string = ''): Promise<QueryStatsByStrict> {
  const res = await apiClient.get('/query/stats/by-strict', { params: userParams(filterUserId) })
  return res.data
}

export async function getQueryStatsLatency(filterUserId: string = ''): Promise<QueryLatencyBreakdown> {
  const res = await apiClient.get('/query/stats/latency', { params: userParams(filterUserId) })
  return res.data
}

export async function getQueryStatsRecords(
  page: number = 1,
  pageSize: number = 20,
  filterUserId: string = '',
  flavor: string = '',
): Promise<{ records: QueryStatsRecord[]; total: number; page: number; page_size: number }> {
  const params: Record<string, string | number> = { page, page_size: pageSize }
  if (filterUserId) params.filter_user_id = filterUserId
  if (flavor) params.flavor = flavor
  const res = await apiClient.get('/query/stats/records', { params })
  return res.data
}

export async function getQueryStatsRecordDetail(
  recordId: number,
  filterUserId: string = '',
): Promise<QueryStatsRecordDetail> {
  const res = await apiClient.get(`/query/stats/records/${recordId}`, {
    params: userParams(filterUserId),
  })
  return res.data
}
