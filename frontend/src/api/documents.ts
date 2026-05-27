/**
 * 通用文档导入 API
 */
import apiClient from './client'

export interface Document {
  document_id: string
  filename: string
  file_type: string
  ingestion_mode: string
  entity_name: string
  status: string
  chunk_count: number
  image_count: number
  error_msg: string
  error_code: string
  retry_count?: number
  last_failed_stage?: string
  cleanup_status?: string
  created_at: string
  updated_at: string
}

export type DocumentChunksSource = 'milvus' | 'parsed_artifact' | 'none'

export interface DocumentChunk {
  chunk_key: string
  sequence: number
  milvus_chunk_id?: number | null
  document_id: string
  file_title: string
  entity_name: string
  content: string
  title: string
  parent_title: string
  section_title: string
  part?: number | null
  page?: number | null
  source_type: string
  table_id?: string | null
  table_title?: string | null
  raw_table_path?: string | null
  table_tokens?: number | null
  image_paths: string[]
  content_length: number
}

export interface DocumentChunksResponse {
  chunks_source: DocumentChunksSource
  document: Document
  chunks: DocumentChunk[]
}

export async function suggestMetadata(filename: string): Promise<{ suggested_entity_name: string }> {
  const res = await apiClient.get('/documents/suggest-metadata', { params: { filename } })
  return res.data
}

export async function uploadDocument(file: File, entityName?: string): Promise<Document> {
  const form = new FormData()
  form.append('file', file)
  form.append('ingestion_mode', 'text_only')
  form.append('entity_name', entityName ?? '')
  const res = await apiClient.post('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export async function listDocuments(): Promise<Document[]> {
  const res = await apiClient.get('/documents')
  return res.data
}

export async function getDocument(documentId: string): Promise<Document> {
  const res = await apiClient.get(`/documents/${documentId}`)
  return res.data
}

export async function getDocumentChunks(documentId: string): Promise<DocumentChunksResponse> {
  const res = await apiClient.get(`/documents/${documentId}/chunks`)
  return res.data
}

export async function processDocument(documentId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.post(`/documents/${documentId}/process`)
  return res.data
}

export async function retryDocument(documentId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.post(`/documents/${documentId}/retry`)
  return res.data
}

export async function deleteDocument(documentId: string): Promise<{ ok: boolean; status?: 'deleted' | 'partial'; detail?: string }> {
  const res = await apiClient.delete(`/documents/${documentId}`)
  return res.data
}

export async function updateDocumentEntity(documentId: string, entityName: string): Promise<{ ok: boolean }> {
  const res = await apiClient.patch(`/documents/${documentId}`, { entity_name: entityName })
  return res.data
}

export async function repairDeleteDocument(documentId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.post(`/documents/${documentId}/repair-delete`)
  return res.data
}
