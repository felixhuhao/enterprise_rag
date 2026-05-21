/**
 * Query Chat API — 知识库查询聊天
 */
import apiClient from './client'

export interface QueryHistoryMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: any[]
  created_at?: string
}

/** 获取指定 session 的聊天历史 */
export async function loadQueryHistory(sessionId: string) {
  const { data } = await apiClient.get('/query/chat/history', {
    params: { session_id: sessionId },
  })
  return data
}
