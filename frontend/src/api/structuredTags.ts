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

export async function listStructuredTags(): Promise<StructuredTagsResponse> {
  const res = await apiClient.get('/admin/structured-tags')
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
