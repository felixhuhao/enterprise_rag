<template>
  <div class="panel">
    <div class="section-header">
      <div class="section-heading">
        <h3>用户管理</h3>
        <span class="section-count">共 {{ users.length }} 个账户 · {{ adminCount }} 管理员</span>
      </div>
      <a-button type="primary" size="small" @click="showCreateUser = true">新建用户</a-button>
    </div>
    <a-spin :loading="loading" style="width: 100%">
      <a-table :data="users" :pagination="false" size="small" row-key="user_id">
        <template #columns>
          <a-table-column title="用户名" data-index="username">
            <template #cell="{ record }">
              <span>{{ record.username }}</span>
              <a-tag v-if="record.user_id === currentUserId" size="small" class="self-tag">当前账户</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="角色" data-index="role" :width="80">
            <template #cell="{ record }">
              <a-tag :color="record.role === 'admin' ? 'red' : 'blue'" size="small">
                {{ record.role === 'admin' ? '管理员' : '用户' }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column title="创建时间" :width="150">
            <template #cell="{ record }">
              <span class="muted">{{ formatDate(record.created_at) }}</span>
            </template>
          </a-table-column>
          <a-table-column title="操作" :width="200">
            <template #cell="{ record }">
              <a-button size="mini" @click="openResetPassword(record)">重置密码</a-button>
              <a-popconfirm content="确认删除该用户？" @ok="handleDeleteUser(record.user_id)">
                <a-button size="mini" status="danger" :disabled="record.is_bootstrap">删除</a-button>
              </a-popconfirm>
            </template>
          </a-table-column>
        </template>
      </a-table>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  listUsers,
  createUser,
  resetPassword,
  deleteUser,
  type UserInfo,
} from '../../api/adminUsers'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const currentUserId = computed(() => authStore.currentUser?.user_id || '')
const adminCount = computed(() => users.value.filter((u) => u.role === 'admin').length)

function formatDate(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

const loading = ref(false)
const actionLoading = ref(false)
const users = ref<UserInfo[]>([])
const showCreateUser = ref(false)
const showResetPassword = ref(false)
const resetTarget = ref<UserInfo | null>(null)
const createForm = reactive({ username: '', password: '', role: 'user' })
const resetForm = reactive({ password: '' })

onMounted(() => loadData())

async function loadData() {
  loading.value = true
  try {
    users.value = await listUsers()
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
    Message.success('密码已重置，该用户的所有会话已失效')
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
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.section-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.section-count {
  color: var(--text-muted);
  font-size: 12px;
}

.self-tag {
  margin-left: 6px;
  background: var(--bg-hover);
  color: var(--text-muted);
}

.muted {
  color: var(--text-muted);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
