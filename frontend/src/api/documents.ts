/**
 * 通用文档导入 API
 */
import apiClient from './client'

export interface Document {
  document_id: string
  filename: string
  file_type: string
  ingestion_mode: string
  status: string
  chunk_count: number
  image_count: number
  error_msg: string
  created_at: string
  updated_at: string
}

export async function uploadDocument(file: File): Promise<Document> {
  const form = new FormData()
  form.append('file', file)
  form.append('ingestion_mode', 'text_only')
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

export async function processDocument(documentId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.post(`/documents/${documentId}/process`)
  return res.data
}

export async function retryDocument(documentId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.post(`/documents/${documentId}/retry`)
  return res.data
}

export async function deleteDocument(documentId: string): Promise<{ ok: boolean }> {
  const res = await apiClient.delete(`/documents/${documentId}`)
  return res.data
}
