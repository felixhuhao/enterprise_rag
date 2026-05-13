<!--
  设置页

  提供 API Token 管理、评估阈值调整、检索配置等运行时设置
-->
<template>
  <div class="settings-page">
    <a-card title="系统设置">
      <a-form :model="form" layout="vertical">
        <!-- API Token -->
        <a-form-item label="API Token" extra="更新后立即生效，同时写入 .env 持久化">
          <a-input-password
            v-model="form.token"
            placeholder="输入新的 API Token"
            allow-clear
          />
          <a-button
            type="primary"
            size="small"
            style="margin-top: 8px"
            :loading="tokenSaving"
            @click="saveToken"
          >
            更新 Token
          </a-button>
        </a-form-item>

        <a-divider />

        <!-- 评估阈值 -->
        <a-form-item label="评估阈值">
          <a-space direction="vertical" fill>
            <div class="threshold-row">
              <span class="threshold-label">高阈值（自动批准）:</span>
              <a-input-number
                v-model="form.evaluate_threshold_high"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
              />
            </div>
            <div class="threshold-row">
              <span class="threshold-label">低阈值（自动拒绝）:</span>
              <a-input-number
                v-model="form.evaluate_threshold_low"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
              />
            </div>
          </a-space>
        </a-form-item>

        <a-divider />

        <!-- 检索配置 -->
        <a-form-item label="检索配置">
          <a-space direction="vertical" fill>
            <div class="threshold-row">
              <span class="threshold-label">Top-K 结果数量:</span>
              <a-input-number v-model="form.retriever_top_k" :min="1" :max="20" />
            </div>
            <div class="threshold-row">
              <span class="threshold-label">默认用户名:</span>
              <a-input v-model="form.default_user_name" style="width: 200px" />
            </div>
          </a-space>
        </a-form-item>

        <a-divider />

        <a-space>
          <a-button type="primary" :loading="saving" @click="saveSettings">保存设置</a-button>
          <a-button @click="loadSettings">恢复当前值</a-button>
        </a-space>
      </a-form>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { getSettings, updateSettings, updateToken } from '../../api/settings'

const saving = ref(false)
const tokenSaving = ref(false)

const form = reactive({
  token: '',
  evaluate_threshold_high: 0.8,
  evaluate_threshold_low: 0.6,
  retriever_top_k: 3,
  default_user_name: 'ZS',
})

async function loadSettings() {
  const data = await getSettings()
  form.evaluate_threshold_high = parseFloat(data.evaluate_threshold_high || '0.8')
  form.evaluate_threshold_low = parseFloat(data.evaluate_threshold_low || '0.6')
  form.retriever_top_k = parseInt(data.retriever_top_k || '3')
  form.default_user_name = data.default_user_name || 'ZS'
  // Token 不回显（后端不返回当前 token）
  form.token = ''
}

async function saveSettings() {
  saving.value = true
  try {
    await updateSettings({
      evaluate_threshold_high: String(form.evaluate_threshold_high),
      evaluate_threshold_low: String(form.evaluate_threshold_low),
      retriever_top_k: String(form.retriever_top_k),
      default_user_name: form.default_user_name,
    })
    window.alert('设置已保存')
  } finally {
    saving.value = false
  }
}

async function saveToken() {
  if (!form.token.trim()) return
  tokenSaving.value = true
  try {
    await updateToken(form.token.trim())
    localStorage.setItem('api_token', form.token.trim())
    form.token = ''
    window.alert('Token 已更新，立即生效')
  } finally {
    tokenSaving.value = false
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.settings-page {
  max-width: 640px;
  margin: 0 auto;
}
.threshold-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.threshold-label {
  width: 180px;
  font-size: 14px;
  color: #4e5969;
}
</style>
