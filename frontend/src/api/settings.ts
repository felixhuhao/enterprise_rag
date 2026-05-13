/**
 * 设置 API
 */
import apiClient from './client'

/** 获取所有设置项 */
export async function getSettings(): Promise<Record<string, string>> {
  const res = await apiClient.get('/settings')
  return res.data
}

/** 批量更新设置项 */
export async function updateSettings(settings: Record<string, string>): Promise<Record<string, string>> {
  const res = await apiClient.put('/settings', { settings })
  return res.data
}

/** 更新 API Token */
export async function updateToken(token: string): Promise<void> {
  await apiClient.post('/settings/token', { token })
}
