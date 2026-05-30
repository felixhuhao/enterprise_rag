<!--
  权限审计页 — 查看所有文档的 ACL 分配，admin only。
-->
<template>
  <div class="acl-page">
    <div v-if="!authStore.isAdmin" class="acl-forbidden">
      <a-empty description="仅管理员可查看权限审计" />
    </div>

    <a-spin v-else :loading="loading" style="width: 100%">
      <div v-if="data" class="acl-users">
        <span class="users-label">用户：</span>
        <span v-for="u in data.users" :key="u.user_id" class="user-badge" :class="'role-' + u.role">
          {{ u.username }}{{ u.role === 'admin' ? ' · 管理员' : '' }}
        </span>
      </div>
      <div v-if="data" class="acl-table-wrap">
        <a-table :data="data.documents" :pagination="{ pageSize: 20 }" row-key="document_id" size="small" :bordered="false">
          <template #columns>
            <a-table-column title="文档" data-index="filename" :ellipsis="true" />
            <a-table-column title="主体" data-index="entity_name" :width="120" />
            <a-table-column title="状态" :width="92" align="center">
              <template #cell="{ record }">
                <a-tag :color="statusColor(record.status)" size="small">
                  {{ statusLabel(record.status) }}
                </a-tag>
	            </template>
            </a-table-column>
            <a-table-column title="清理" :width="72" align="center">
              <template #cell="{ record }">
                <span v-if="record.cleanup_status === 'milvus_delete_failed'" class="cleanup-warn">待清理</span>
                <span v-else class="cleanup-ok">—</span>
              </template>
            </a-table-column>
            <a-table-column title="权限" :width="420">
              <template #cell="{ record }">
                <div class="perm-list">
                  <span v-if="!record.permissions.length" class="perm-empty">未授权</span>
                  <span v-for="p in record.permissions" :key="p.user_id" class="perm-tag" :class="'perm-' + p.permission">
                    {{ p.username }}({{ permLabel(p.permission) }})
                  </span>
                </div>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { getAclAudit, type AclAuditResponse } from '../../api/adminAcl'

const authStore = useAuthStore()
const loading = ref(false)
const data = ref<AclAuditResponse | null>(null)

onMounted(async () => {
  if (!authStore.currentUser) await authStore.fetchMe()
  if (!authStore.isAdmin) return
  loading.value = true
  try {
    data.value = await getAclAudit()
  } finally {
    loading.value = false
  }
})

function statusLabel(s: string) {
  const map: Record<string, string> = { completed: '已完成', failed: '失败', uploaded: '已上传' }
  return map[s] ?? s
}
function statusColor(s: string) {
  if (s === 'completed') return 'green'
  if (s === 'failed') return 'red'
  return 'arcoblue'
}
function permLabel(p: string) { return p === 'owner' ? '管理' : '只读' }
</script>

<style scoped>
.acl-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.acl-users {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-base);
}
.users-label { font-size: 12px; color: var(--text-muted); }
.user-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  border: 1px solid var(--border); color: var(--text-secondary);
}
.role-admin { color: #92400e; border-color: #fcd34d; background: #fef3c7; }

.acl-forbidden { padding: 60px 0; }

.cleanup-warn { color: #c2410c; font-size: 12px; font-weight: 600; }
.cleanup-ok { color: var(--text-muted); }

.perm-list {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.perm-empty { color: var(--text-muted); font-size: 12px; }
.perm-tag {
  display: inline-block;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
}
.perm-read { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
.perm-owner { background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }
</style>
