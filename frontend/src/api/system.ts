import apiClient from './client'

export interface RuntimeInfo {
  chat_model: string
  chat_timeout: number
  embedding_model: string
  embedding_dim: number
  embedding_device: string
  milvus_uri: string
  database_path: string
}

export async function getRuntimeInfo(): Promise<RuntimeInfo> {
  const res = await apiClient.get('/system/runtime-info')
  return res.data
}
