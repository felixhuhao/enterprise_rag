import apiClient from './client'

export interface AclUser {
  user_id: string
  username: string
  role: string
}

export interface AclPermission {
  user_id: string
  username: string
  role: string
  permission: string
}

export interface AclDocument {
  document_id: string
  filename: string
  entity_name: string
  status: string
  cleanup_status: string
  permissions: AclPermission[]
}

export interface AclAuditResponse {
  users: AclUser[]
  documents: AclDocument[]
}

export async function getAclAudit(): Promise<AclAuditResponse> {
  const res = await apiClient.get('/admin/acl/documents')
  return res.data
}
