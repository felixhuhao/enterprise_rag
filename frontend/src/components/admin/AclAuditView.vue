<template>
  <div class="acl-view">
    <a-spin :loading="loading" style="width: 100%">
      <div v-if="authStore.isAdmin" class="acl-content">
        <!-- 用户管理 -->
        <a-card title="用户管理" class="section-card">
          <div class="card-actions">
            <a-button type="primary" size="small" @click="showCreateUser = true">新建用户</a-button>
          </div>
          <a-table :data="users" :pagination="false" size="small" row-key="user_id">
            <template #columns>
              <a-table-column title="用户名" data-index="username" />
              <a-table-column title="角色" data-index="role" :width="80">
                <template #cell="{ record }">
                  <a-tag :color="record.role === 'admin' ? 'red' : 'blue'" size="small">
                    {{ record.role === 'admin' ? '管理员' : '用户' }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="200">
                <template #cell="{ record }">
                  <a-button size="mini" @click="openResetPassword(record)">重置密码</a-button>
                  <a-popconfirm content="确认删除该用户？" @ok="handleDeleteUser(record.user_id)">
                    <a-button size="mini" status="danger" :disabled="record.user_id === bootstrapId">删除</a-button>
                  </a-popconfirm>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </a-card>

        <!-- 实体权限 -->
        <a-card title="实体权限" class="section-card">
          <a-table :data="entityData" :pagination="{ pageSize: 10 }" size="small" row-key="entity_name">
            <template #columns>
              <a-table-column title="实体名称" data-index="entity_name" />
              <a-table-column title="文档数" data-index="document_count" :width="80" />
              <a-table-column title="授权">
                <template #cell="{ record }">
                  <div class="grant-list">
                    <a-tag
                      v-for="g in record.grants"
                      :key="g.user_id"
                      :color="g.permission === 'write' ? 'green' : 'arcoblue'"
                      size="small"
                      closable
                      @close="handleRevoke(record.entity_name, g.user_id)"
                    >
                      {{ g.username }} ({{ g.permission === 'write' ? '写' : '读' }})
                    </a-tag>
                    <a-button size="mini" @click="openGrant(record.entity_name)">授权</a-button>
                  </div>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </a-card>
      </div>
      <a-empty v-else description="仅管理员可访问" />
    </a-spin>

    <!-- 新建用户对话框 -->
    <a-modal v-model:visible="showCreateUser" title="新建用户" :footer="false">
      <a-form :model="createForm" layout="vertical">
        <a-form-item label="用户名" required>
          <a-input v-model="createForm.username" placeholder="输入用户名" />
        </a-form-item>
        <a-form-item label="密码（至少8位）" required>
          <a-input-password v-model="createForm.password" placeholder="输入密码" />
        </a-form-item>
        <a-form-item label="角色">
          <a-select v-model="createForm.role">
            <a-option value="user">用户</a-option>
            <a-option value="admin">管理员</a-option>
          </a-select>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="showCreateUser = false">取消</a-button>
          <a-button type="primary" :loading="actionLoading" @click="handleCreateUser">创建</a-button>
        </div>
      </a-form>
    </a-modal>

    <!-- 重置密码对话框 -->
    <a-modal v-model:visible="showResetPassword" title="重置密码" :footer="false">
      <p>正在为 <strong>{{ resetTarget?.username }}</strong> 重置密码</p>
      <a-input-password v-model="resetForm.password" placeholder="输入新密码（至少8位）" style="margin-bottom: 12px" />
      <div class="modal-actions">
        <a-button @click="showResetPassword = false">取消</a-button>
        <a-button type="primary" :loading="actionLoading" @click="handleResetPassword">确认</a-button>
      </div>
    </a-modal>

    <!-- 授权对话框 -->
    <a-modal v-model:visible="showGrant" title="授予实体权限" :footer="false">
      <p>实体: <strong>{{ grantEntity }}</strong></p>
      <a-select v-model="grantForm.userId" placeholder="选择用户" style="width: 100%; margin-bottom: 12px">
        <a-option v-for="u in users" :key="u.user_id" :value="u.user_id">{{ u.username }}</a-option>
      </a-select>
      <a-select v-model="grantForm.permission" style="width: 100%; margin-bottom: 12px">
        <a-option value="read">读 (read)</a-option>
        <a-option value="write">写 (write)</a-option>
      </a-select>
      <div class="modal-actions">
        <a-button @click="showGrant = false">取消</a-button>
        <a-button type="primary" :loading="actionLoading" @click="handleGrant">确认</a-button>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'
import {
  listUsers,
  createUser,
  resetPassword,
  deleteUser,
  getEntityAclOverview,
  grantEntityAccess,
  revokeEntityAccess,
  type UserInfo,
  type EntityAclEntry,
} from '../../api/adminUsers'

const authStore = useAuthStore()
const loading = ref(false)
const actionLoading = ref(false)
const users = ref<UserInfo[]>([])
const entityData = ref<EntityAclEntry[]>([])
const bootstrapId = ref('u_admin')

const showCreateUser = ref(false)
const showResetPassword = ref(false)
const showGrant = ref(false)
const resetTarget = ref<UserInfo | null>(null)
const grantEntity = ref('')

const createForm = reactive({ username: '', password: '', role: 'user' })
const resetForm = reactive({ password: '' })
const grantForm = reactive({ userId: '', permission: 'read' })

onMounted(async () => {
  if (!authStore.currentUser) await authStore.fetchMe()
  if (!authStore.isAdmin) return
  await loadData()
})

async function loadData() {
  loading.value = true
  try {
    const [u, e] = await Promise.all([listUsers(), getEntityAclOverview()])
    users.value = u
    entityData.value = e.entities
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function handleCreateUser() {
  if (!createForm.username.trim() || createForm.password.length < 8) {
    Message.warning('用户名不能为空，密码至少8位')
    return
  }
  actionLoading.value = true
  try {
    await createUser({ ...createForm })
    Message.success('用户创建成功')
    showCreateUser.value = false
    createForm.username = ''
    createForm.password = ''
    await loadData()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '创建失败')
  } finally {
    actionLoading.value = false
  }
}

function openResetPassword(user: UserInfo) {
  resetTarget.value = user
  resetForm.password = ''
  showResetPassword.value = true
}

async function handleResetPassword() {
  if (!resetTarget.value || resetForm.password.length < 8) {
    Message.warning('密码至少8位')
    return
  }
  actionLoading.value = true
  try {
    await resetPassword(resetTarget.value.user_id, resetForm.password)
    Message.success('密码已重置')
    showResetPassword.value = false
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '重置失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleDeleteUser(userId: string) {
  try {
    await deleteUser(userId)
    Message.success('用户已删除')
    await loadData()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '删除失败')
  }
}

function openGrant(entityName: string) {
  grantEntity.value = entityName
  grantForm.userId = ''
  grantForm.permission = 'read'
  showGrant.value = true
}

async function handleGrant() {
  if (!grantForm.userId) {
    Message.warning('请选择用户')
    return
  }
  actionLoading.value = true
  try {
    await grantEntityAccess(grantEntity.value, grantForm.userId, grantForm.permission)
    Message.success('授权成功')
    showGrant.value = false
    await loadData()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '授权失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleRevoke(entityName: string, userId: string) {
  try {
    await revokeEntityAccess(entityName, userId)
    Message.success('已撤销')
    await loadData()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '撤销失败')
  }
}
</script>

<style scoped>
.acl-view {
  height: 100%;
  overflow-y: auto;
}

.acl-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-card {
  width: 100%;
}

.card-actions {
  margin-bottom: 12px;
}

.grant-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
