<!--
  设置页

  API Token、查询模式预设、候选结果数
-->
<template>
  <div class="settings-page">
    <div class="settings-card">
      <!-- API Token -->
      <section class="settings-section">
        <div class="section-title">API Token</div>
        <div class="section-hint">更新后立即生效，同时写入 .env 持久化</div>
        <div class="token-row">
          <a-input-password
            v-model="form.token"
            placeholder="输入新的 API Token"
            allow-clear
          />
          <a-button type="primary" :loading="tokenSaving" @click="saveToken">
            更新
          </a-button>
        </div>
      </section>

      <a-divider />

      <!-- 查询模式 -->
      <section class="settings-section">
        <div class="section-title">查询模式</div>
        <div class="section-hint">选择经过验证的查询策略，避免随机组合</div>
        <div class="mode-selector">
          <div
            v-for="p in presets"
            :key="p.id"
            class="mode-card"
            :class="{ active: selectedPreset === p.id }"
            @click="applyPreset(p.id)"
          >
            <div class="mode-main">
              <div>
                <div class="mode-name">{{ p.name }}</div>
                <div class="mode-desc">{{ p.desc }}</div>
              </div>
              <span v-if="p.id === 'balanced'" class="mode-badge">推荐</span>
            </div>
            <div class="mode-features">
              <span v-for="f in p.features" :key="f" class="feature-dot">{{ f }}</span>
            </div>
          </div>
        </div>
      </section>

      <a-divider />

      <!-- 候选结果数 -->
      <section class="settings-section">
        <div class="section-title">候选结果数</div>
        <div class="section-hint">数值越大召回越充分，但延迟可能增加</div>
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
const selectedPreset = ref('balanced')

interface PresetDef {
  id: string
  name: string
  desc: string
  features: string[]
  toggles: Record<string, boolean>
}

const presets: PresetDef[] = [
  {
    id: 'fast',
    name: '基础 Fast',
    desc: '最快，适合简单查询',
    features: ['表格扩展'],
    toggles: {
      use_entity_confirm: false,
      use_rewrite: false,
      use_table_expand: true,
      use_hyde: false,
      use_rerank: false,
    },
  },
  {
    id: 'balanced',
    name: '标准 Balanced',
    desc: '推荐，平衡准确率和速度',
    features: ['主体确认', '改写', '表格扩展', 'Rerank'],
    toggles: {
      use_entity_confirm: true,
      use_rewrite: true,
      use_table_expand: true,
      use_hyde: false,
      use_rerank: true,
    },
  },
  {
    id: 'accurate',
    name: '高级 Accurate',
    desc: '最强，适合复杂问题',
    features: ['主体确认', '改写', '表格扩展', 'HyDE', 'Rerank'],
    toggles: {
      use_entity_confirm: true,
      use_rewrite: true,
      use_table_expand: true,
      use_hyde: true,
      use_rerank: true,
    },
  },
]

const form = reactive({
  token: '',
  queryBools: { ...presets[1].toggles } as Record<string, boolean>,
  searchLimit: 10,
})

function parseBool(v: string): boolean {
  return v.toLowerCase() === 'true' || v === '1'
}

function detectPreset(booleans: Record<string, boolean>): string {
  for (const p of presets) {
    if (Object.entries(p.toggles).every(([k, v]) => booleans[k] === v)) {
      return p.id
    }
  }
  return 'balanced'
}

function applyPreset(id: string) {
  const p = presets.find((x) => x.id === id)
  if (p) {
    Object.assign(form.queryBools, p.toggles)
    selectedPreset.value = id
  }
}

async function loadSettings() {
  const data = await getSettings()
  form.token = ''

  const boolKeys = Object.keys(presets[0].toggles)
  for (const key of boolKeys) {
    const raw = data[`query.${key}`]
    form.queryBools[key] = raw !== undefined && raw !== '' ? parseBool(raw) : presets[1].toggles[key]
  }

  const rawLimit = data['query.search_limit']
  form.searchLimit = rawLimit !== undefined && rawLimit !== '' ? parseInt(rawLimit, 10) : 10

  selectedPreset.value = detectPreset(form.queryBools)
}

async function saveSettings() {
  saving.value = true
  try {
    const updates: Record<string, string> = {}
    for (const [key, val] of Object.entries(form.queryBools)) {
      updates[`query.${key}`] = String(val)
    }
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
  animation: fadeIn 0.3s var(--ease-out);
}

.settings-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
}

.settings-section {
  margin-bottom: 4px;
}

.section-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.section-hint {
  margin-top: 4px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-muted);
}

.token-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.mode-selector {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.mode-card {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
  user-select: none;
}

.mode-card:hover {
  border-color: var(--text-muted);
}

.mode-card.active {
  border-color: var(--accent);
  background: var(--accent-subtle);
}

.mode-main {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.mode-name {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.mode-card.active .mode-name {
  color: var(--accent);
}

.mode-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-muted);
}

.mode-badge {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  color: var(--accent);
  border: 1px solid var(--border-accent);
  background: var(--accent-subtle);
  flex-shrink: 0;
}

.mode-features {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.feature-dot {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg-hover);
  color: var(--text-muted);
  border: 1px solid var(--border);
}

.mode-card.active .feature-dot {
  background: var(--accent-subtle);
  border-color: var(--border-accent);
  color: var(--accent);
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
  .settings-page {
    padding: 16px;
  }

  .settings-card {
    padding: 16px;
  }

  .mode-selector {
    grid-template-columns: 1fr;
  }
}
</style>
