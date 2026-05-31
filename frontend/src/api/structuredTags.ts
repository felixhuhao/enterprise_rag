import apiClient from './client'

export interface StructuredTagRecord {
  tag_key: string
  label: string
  default_label: string
  description: string
  default_description: string
  priority: number
  scope: string
  profile: string
  enabled: boolean
  default_enabled: boolean
  ui_visible: boolean
  default_ui_visible: boolean
  overridden: boolean
  updated_at: string
}

export interface StructuredTagsResponse {
  records: StructuredTagRecord[]
  total: number
}

export interface StructuredTagUpdate {
  label?: string
  description?: string
  enabled?: boolean
  ui_visible?: boolean
}

export interface StructuredTagMutationResponse {
  record: StructuredTagRecord
  reindex_required: boolean
}

export interface StructuredTagMetricRow {
  tag_key: string
  label: string
  chunks: number
  documents: number
}

export interface StructuredTagMetrics {
  summary: {
    document_count: number
    chunk_count: number
    zero_tag_chunks: number
    too_many_keywords_chunks: number
  }
  top_tags: StructuredTagMetricRow[]
  top_keywords: Array<{ keyword: string; chunks: number }>
  by_source_type: Array<{ tag_key: string; label: string; source_type: string; chunks: number }>
}

export interface StructuredTagPreviewItem {
  chunk_key: string
  section_title: string
  source_type: string
  structured_tags: Array<{ tag_key: string; label: string }>
  keywords: string[]
  evidence: Array<{ tag_key: string; snippet: string }>
  search_text_length: number
  search_text_preview: string
}

export interface StructuredTagPreviewResponse {
  source: 'text' | 'document'
  document_id: string
  profile: string
  summary: {
    chunk_count: number
    matched_chunks: number
    tag_count: number
  }
  tag_counts: StructuredTagMetricRow[]
  items: StructuredTagPreviewItem[]
}

export async function listStructuredTags(): Promise<StructuredTagsResponse> {
  const res = await apiClient.get('/admin/structured-tags')
  return res.data
}

export async function getStructuredTagMetrics(): Promise<StructuredTagMetrics> {
  const res = await apiClient.get('/admin/structured-tags/metrics')
  return res.data
}

export async function previewStructuredTags(payload: {
  text?: string
  section_title?: string
  document_id?: string
  max_chunks?: number
}): Promise<StructuredTagPreviewResponse> {
  const res = await apiClient.post('/admin/structured-tags/preview', payload)
  return res.data
}

export async function updateStructuredTag(
  tagKey: string,
  payload: StructuredTagUpdate,
): Promise<StructuredTagMutationResponse> {
  const res = await apiClient.patch(`/admin/structured-tags/${encodeURIComponent(tagKey)}`, payload)
  return res.data
}

export async function resetStructuredTag(tagKey: string): Promise<StructuredTagMutationResponse> {
  const res = await apiClient.post(`/admin/structured-tags/${encodeURIComponent(tagKey)}/reset`)
  return res.data
}
