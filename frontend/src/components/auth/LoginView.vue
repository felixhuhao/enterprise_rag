<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <h2>Enterprise RAG</h2>
        <p>请登录以继续</p>
      </div>
      <a-form :model="form" layout="vertical" @submit-success="handleLogin">
        <a-form-item field="username" label="用户名">
          <a-input
            v-model="form.username"
            placeholder="输入用户名"
            allow-clear
            :disabled="loading"
          />
        </a-form-item>
        <a-form-item field="password" label="密码">
          <a-input-password
            v-model="form.password"
            placeholder="输入密码"
            :disabled="loading"
            @keydown.enter="handleLogin"
          />
        </a-form-item>
        <a-button
          type="primary"
          long
          :loading="loading"
          :disabled="!form.username.trim() || !form.password"
          @click="handleLogin"
        >
          登录
        </a-button>
      </a-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  const username = form.username.trim()
  if (!username || !form.password) return
  loading.value = true
  try {
    await authStore.login(username, form.password)
    form.password = ''
    Message.success(`欢迎，${authStore.currentUser?.username}`)
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--bg-body, #f0f2f5);
}

.login-card {
  width: 380px;
  padding: 32px;
  background: var(--bg-surface, #fff);
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.login-header {
  text-align: center;
  margin-bottom: 24px;
}

.login-header h2 {
  margin: 0 0 4px;
  font-size: 22px;
  color: var(--text-primary, #1d2129);
}

.login-header p {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary, #86909c);
}
</style>
