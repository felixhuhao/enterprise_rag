<!--
  设置页

  提供 API Token 管理、评估阈值调整、检索配置等运行时设置
-->
<template>
  <div class="settings-page">
    <div class="settings-card">
      <div class="settings-header">
        <h3>系统设置</h3>
        <p class="settings-desc">管理 API 令牌、评估阈值和检索参数</p>
      </div>

      <a-form :model="form" layout="vertical">
        <!-- API Token -->
        <div class="form-section">
          <div class="section-label">API Token</div>
          <div class="section-hint">更新后立即生效，同时写入 .env 持久化</div>
          <div class="token-row">
            <a-input-password
              v-model="form.token"
              placeholder="输入新的 API Token"
              allow-clear
              style="flex: 1"
            />
            <a-button
              type="primary"
              size="small"
              :loading="tokenSaving"
              @click="saveToken"
            >
              更新 Token
            </a-button>
          </div>
        </div>

        <div class="divider"></div>

        <!-- 评估阈值 -->
        <div class="form-section">
          <div class="section-label">评估阈值</div>
          <div class="threshold-grid">
            <div class="threshold-item">
              <span class="threshold-name">高阈值（自动批准）</span>
              <a-input-number
                v-model="form.evaluate_threshold_high"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
              />
            </div>
            <div class="threshold-item">
              <span class="threshold-name">低阈值（自动拒绝）</span>
              <a-input-number
                v-model="form.evaluate_threshold_low"
                :min="0"
                :max="1"
                :step="0.05"
                :precision="2"
              />
            </div>
          </div>
        </div>

        <div class="divider"></div>

        <!-- 检索配置 -->
        <div class="form-section">
          <div class="section-label">检索配置</div>
          <div class="threshold-grid">
            <div class="threshold-item">
              <span class="threshold-name">Top-K 结果数量</span>
              <a-input-number v-model="form.retriever_top_k" :min="1" :max="20" />
            </div>
            <div class="threshold-item">
              <span class="threshold-name">默认用户名</span>
              <a-input v-model="form.default_user_name" style="width: 200px" />
            </div>
          </div>
        </div>

        <div class="divider"></div>

        <div class="form-actions">
          <a-button type="primary" :loading="saving" @click="saveSettings">保存设置</a-button>
          <a-button @click="loadSettings">恢复当前值</a-button>
        </div>
      </a-form>
    </div>
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
  animation: fadeIn 0.3s var(--ease-out);
}

.settings-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 28px;
}

.settings-header {
  margin-bottom: 24px;
}
.settings-header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.settings-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

/* Form sections */
.form-section {
  padding: 4px 0;
}

.section-label {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.section-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.token-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

/* Threshold grid */
.threshold-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 8px;
}

.threshold-item {
  display: flex;
  align-items: center;
  gap: 16px;
}

.threshold-name {
  width: 180px;
  font-size: 13px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

/* Divider */
.divider {
  height: 1px;
  background: var(--border);
  margin: 20px 0;
}

/* Actions */
.form-actions {
  display: flex;
  gap: 12px;
}
</style>
