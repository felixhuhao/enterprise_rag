/**
 * 会话管理 API
 *
 * 封装与后端 /api/sessions 相关的 HTTP 请求
 */
import apiClient from './client'

/** 会话信息（与后端 schemas.py SessionInfo 对应） */
export interface SessionInfo {
  session_id: string
  user_name: string
  created_at: string
  status: string
}

/** 创建新的聊天会话 */
export async function createSession(userName = 'ZS'): Promise<SessionInfo> {
  const res = await apiClient.post('/sessions', { user_name: userName })
  return res.data
}

/** 获取所有会话列表 */
export async function listSessions(): Promise<SessionInfo[]> {
  const res = await apiClient.get('/sessions')
  return res.data
}

/** 删除指定会话 */
export async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/sessions/${sessionId}`)
}
