import apiClient from './client'

export interface UserInfo {
  user_id: string
  username: string
  role: string
  created_at: string
}

export interface CreateUserParams {
  username: string
  password: string
  role: string
}

export async function listUsers(): Promise<UserInfo[]> {
  const res = await apiClient.get('/admin/users')
  return res.data
}

export async function createUser(params: CreateUserParams): Promise<UserInfo> {
  const res = await apiClient.post('/admin/users', params)
  return res.data
}

export async function resetPassword(userId: string, password: string): Promise<void> {
  await apiClient.post(`/admin/users/${userId}/reset-password`, { password })
}

export async function deleteUser(userId: string): Promise<void> {
  await apiClient.delete(`/admin/users/${userId}`)
}

export async function listEntities(): Promise<string[]> {
  const res = await apiClient.get('/admin/entities')
  return res.data
}

export async function grantEntityAccess(entityName: string, userId: string, permission: string): Promise<void> {
  await apiClient.post('/admin/acl/grant', { entity_name: entityName, user_id: userId, permission })
}

export async function revokeEntityAccess(entityName: string, userId: string): Promise<void> {
  await apiClient.post('/admin/acl/revoke', { entity_name: entityName, user_id: userId })
}

export interface EntityGrant {
  user_id: string
  username: string
  role: string
  permission: string
}

export interface EntityAclEntry {
  entity_name: string
  document_count: number
  grants: EntityGrant[]
}

export async function getEntityAclOverview(): Promise<{ entities: EntityAclEntry[] }> {
  const res = await apiClient.get('/admin/acl/entities')
  return res.data
}
