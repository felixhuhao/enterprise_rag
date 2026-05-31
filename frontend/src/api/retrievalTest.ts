/**
 * 检索测试 API
 */
import apiClient from './client'

export interface RetrievalTestRequest {
  query: string
  top_k: number
  use_hybrid: boolean
  use_hyde: boolean
  use_rerank: boolean
  retrieval_flavor?: string
  strict_evidence?: boolean
}

export interface RetrievalStrategy {
  top_k: number
  hybrid: boolean
  hyde: boolean
  query_expansion?: boolean
  rerank: boolean
  table_expand: boolean
  fallback: boolean
  search_mode: string
  search_mode_hyde: string
  embedding_model: string
  chat_model: string
  dense_weight: number
  sparse_weight: number
  retrieval_flavor: string
  strict_evidence: boolean
}

export interface RetrievalBudget {
  search_limit?: number
  hyde_limit?: number
  rrf_top_k?: number
  rerank_candidate_k?: number
  final_context_k?: number
  max_context_chars?: number
  per_entity_min_k?: number
  reason?: string
}

export interface QueryPlan {
  retrieval_flavor?: string
  strict_evidence?: boolean
  budget?: RetrievalBudget
  [key: string]: unknown
}

export interface HopTraceEntry {
  hop: number
  query?: string
  entity_filter?: string
  result_count: number
  status: string
  discovered_entities?: string[]
  per_entity_counts?: Record<string, number>
}

export interface QueryExpansionTraceEntry {
  label: string
  query: string
  count: number
}

export interface AliasTraceEntry {
  alias: string
  canonical?: string
  canonicals?: string[]
  ambiguous: boolean
}

export interface RetrievalResult {
  rank: number
  chunk_id?: number | null
  chunk_key?: string
  document_id: string
  file_title: string
  entity_name: string
  section_title: string
  page?: number | null
  source_type: string
  keywords?: string[]
  structured_tags?: string[]
  table_id?: string
  table_title?: string
  score: number
  llm_score?: number | null
  rrf_score?: number | null
  final_score?: number | null
  retrieval_path: string
  retrieval_paths: string[]
  context_expanded_chunk_ids?: number[]
  context_expand_parts?: number[]
  content: string
  content_preview: string
}

export interface RetrievalTestResponse {
  query: string
  rewritten_query: string
  confirmed_entity: string
  entity_filter: string
  entity_mode: string
  matched_entities: string[]
  per_entity_counts: Record<string, number>
  alias_trace?: AliasTraceEntry[]
  expanded_queries?: string[]
  per_query_counts?: Record<string, number>
  query_expansion_trace?: QueryExpansionTraceEntry[]
  hop_plan?: string
  hop_trace?: HopTraceEntry[]
  retrieval_flavor: string
  strict_evidence: boolean
  query_plan: QueryPlan
  fallback_info: {
    used: boolean
    blocked: boolean
    type: string
    reason: string
    original_filter: string
  }
  result_count: number
  trace: Record<string, number>
  strategy: RetrievalStrategy
  results: RetrievalResult[]
}

export async function runRetrievalTest(payload: RetrievalTestRequest): Promise<RetrievalTestResponse> {
  const res = await apiClient.post('/query/retrieval-test', payload, { timeout: 120000 })
  return res.data
}
