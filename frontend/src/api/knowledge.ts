/**
 * 知识库管理 API
 */
import apiClient from './client'

export interface KnowledgeDocument {
  id: number
  filename: string
  source: string
  status: 'uploaded' | 'parsing' | 'parsed' | 'saving' | 'completed' | 'failed'
  doc_count: number
  image_count: number
  error_msg: string
  created_at: string
  updated_at: string
}

/** 上传 PDF 文件 */
export async function uploadDocument(file: File): Promise<KnowledgeDocument> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiClient.post('/knowledge/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return res.data
}

/** 获取文档列表 */
export async function listDocuments(): Promise<KnowledgeDocument[]> {
  const res = await apiClient.get('/knowledge/documents')
  return res.data
}

/** 获取单个文档状态（轮询用） */
export async function getDocument(docId: number): Promise<KnowledgeDocument> {
  const res = await apiClient.get(`/knowledge/documents/${docId}`)
  return res.data
}

/** 一键处理文档（解析+入库） */
export async function processDocument(docId: number): Promise<void> {
  await apiClient.post(`/knowledge/documents/${docId}/process`)
}

/** 删除文档 */
export async function deleteDocument(docId: number): Promise<void> {
  await apiClient.delete(`/knowledge/documents/${docId}`)
}
