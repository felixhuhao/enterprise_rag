import apiClient from './client'
import type { CurrentUser } from '../stores/auth'

export interface LoginResponse {
  token: string
  user: CurrentUser
  expires_at: string
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await apiClient.post('/auth/login', { username, password })
  return res.data
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}
