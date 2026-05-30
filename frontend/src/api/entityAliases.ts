import apiClient from './client'

export interface EntityAliasRecord {
  id: number
  alias: string
  canonical_entity: string
  source: string
  created_at: string
}

export interface EntityAliasListResponse {
  records: EntityAliasRecord[]
  total: number
  page: number
  page_size: number
}

export interface EntityAliasBatchItem {
  alias: string
  canonical_entity: string
  source?: string
}

export interface EntityAliasBatchResponse {
  created: number
  skipped: number
  errors: Array<{ alias: string; canonical_entity: string; error: string }>
}

export async function listEntityAliases(page = 1, pageSize = 100): Promise<EntityAliasListResponse> {
  const res = await apiClient.get('/admin/entity-aliases', {
    params: { page, page_size: pageSize },
  })
  return res.data
}

export async function createEntityAlias(
  alias: string,
  canonicalEntity: string,
  source = 'admin',
): Promise<EntityAliasRecord> {
  const res = await apiClient.post('/admin/entity-aliases', {
    alias,
    canonical_entity: canonicalEntity,
    source,
  })
  return res.data
}

export async function batchCreateEntityAliases(
  items: EntityAliasBatchItem[],
): Promise<EntityAliasBatchResponse> {
  const res = await apiClient.post('/admin/entity-aliases/batch', items)
  return res.data
}

export async function deleteEntityAlias(id: number): Promise<void> {
  await apiClient.delete(`/admin/entity-aliases/${id}`)
}
