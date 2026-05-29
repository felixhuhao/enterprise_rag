<!--
  设置页

  API Token、候选结果数
-->
<template>
  <div class="settings-page">
    <div class="settings-card">
      <!-- API Token -->
      <section class="settings-section">
        <div class="section-heading">
          <div>
            <div class="section-title">访问令牌</div>
            <div class="section-hint">更新后立即生效，同时写入 .env 持久化</div>
          </div>
          <span class="section-kicker">安全</span>
        </div>
        <div class="token-row">
          <a-input-password
            v-model="form.token"
            placeholder="输入新的访问令牌"
            allow-clear
          />
          <a-button type="primary" :loading="tokenSaving" @click="saveToken">
            更新
          </a-button>
        </div>
      </section>

      <a-divider />

      <!-- 候选结果数 -->
      <section class="settings-section">
        <div class="section-heading">
          <div>
            <div class="section-title">候选结果数</div>
            <div class="section-hint">数值越大召回越充分，但延迟可能增加</div>
          </div>
          <span class="section-kicker">检索</span>
        </div>
        <div class="limit-row">
          <a-slider
            v-model="form.searchLimit"
            :min="5"
            :max="30"
            :step="1"
            show-input
            :style="{ maxWidth: '400px' }"
          />
        </div>
      </section>

      <a-divider />

      <!-- 操作按钮 -->
      <section class="settings-actions">
        <a-button type="primary" :loading="saving" @click="saveSettings">保存设置</a-button>
        <a-button @click="loadSettings">恢复当前值</a-button>
      </section>
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
  searchLimit: 10,
})

async function loadSettings() {
  const data = await getSettings()
  form.token = ''

  const rawLimit = data['query.search_limit']
  form.searchLimit = rawLimit !== undefined && rawLimit !== '' ? parseInt(rawLimit, 10) : 10
}

async function saveSettings() {
  saving.value = true
  try {
    const updates: Record<string, string> = {}
    updates['query.search_limit'] = String(form.searchLimit)
    await updateSettings(updates)
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
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.settings-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  max-width: 1120px;
}

.settings-section {
  margin-bottom: 4px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.section-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.section-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.section-kicker {
  flex-shrink: 0;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
  font-size: 11px;
}

.token-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.limit-row {
  display: flex;
  align-items: center;
}

.settings-actions {
  display: flex;
  gap: 10px;
}

.settings-actions :deep(.arco-divider) {
  margin: 16px 0;
}

@media (max-width: 768px) {
  .settings-card {
    padding: 16px;
  }
}
</style>
