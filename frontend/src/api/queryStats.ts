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
  rank: number
  score: number
  document_id?: string
  file_title?: string
  entity_name?: string
  section_title?: string
  source_type?: string
  retrieval_path?: string
  stage?: string
}

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
  groundedness_score?: number | null
  created_at: string
}

export async function getQueryStats(): Promise<QueryStats> {
  const res = await apiClient.get('/query/stats')
  return res.data
}

export async function getQueryStatsTrend(): Promise<QueryStatsTrend> {
  const res = await apiClient.get('/query/stats/trend')
  return res.data
}

export async function getQueryStatsRecords(
  page: number = 1,
  pageSize: number = 20,
): Promise<{ records: QueryStatsRecord[]; total: number; page: number; page_size: number }> {
  const res = await apiClient.get('/query/stats/records', { params: { page, page_size: pageSize } })
  return res.data
}
