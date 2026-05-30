<!--
  系统设置页
-->
<template>
  <div class="settings-page">
    <div class="settings-card">
      <a-tabs default-active-key="status" class="settings-tabs" animation>
        <template #extra>
          <a-button size="mini" :loading="loading" @click="loadSettings">刷新</a-button>
        </template>
        <a-tab-pane key="status" title="运行状态">
          <div class="status-grid">
            <div class="status-card">
              <span class="status-label">后端 API</span>
              <strong :class="loadError ? 'bad' : 'ok'">{{ loadError ? '异常' : '正常' }}</strong>
              <small>{{ loadError || '设置接口可访问' }}</small>
            </div>
            <div class="status-card">
              <span class="status-label">当前用户</span>
              <strong>{{ authStore.currentUser?.username || '未知' }}</strong>
              <small>{{ authStore.currentUser?.user_id || '未读取到用户信息' }}</small>
            </div>
            <div class="status-card">
              <span class="status-label">权限</span>
              <strong>{{ authStore.isAdmin ? '管理员' : '普通用户' }}</strong>
              <small>{{ authStore.isAdmin ? '可修改系统设置' : '仅可查看当前设置' }}</small>
            </div>
            <div class="status-card">
              <span class="status-label">配置加载</span>
              <strong :class="settingsCount ? 'ok' : ''">{{ settingsCount ? '已加载' : '未加载' }}</strong>
              <small>{{ loadedAt || '尚未刷新' }}</small>
            </div>
          </div>

          <div class="info-panel">
            <div class="panel-title">模型与服务</div>
            <div class="info-list">
              <div class="info-row">
                <span>聊天模型</span>
                <strong>{{ runtimeInfo?.chat_model || '未读取' }}</strong>
              </div>
              <div class="info-row">
                <span>Embedding</span>
                <strong>{{ embeddingLabel }}</strong>
              </div>
              <div class="info-row">
                <span>向量库（backend）</span>
                <strong>{{ backendMilvusLabel }}</strong>
              </div>
              <div class="info-row">
                <span>向量库（宿主机）</span>
                <strong>{{ hostMilvusUri }}</strong>
              </div>
              <div class="info-row">
                <span>数据库（backend）</span>
                <strong>{{ backendDatabaseLabel }}</strong>
              </div>
              <div class="info-row">
                <span>Token</span>
                <strong>{{ tokenStatus }}</strong>
              </div>
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="tuning" title="策略微调">
          <div v-if="!authStore.isAdmin" class="readonly-note">当前用户没有修改权限。</div>
          <div class="strategy-note">
            当前版本仍使用一组全局参数；这里按后端 planner 展示每种策略真正会使用的部分。固定预算只读显示，避免产生“改了但不生效”的误解。
          </div>

          <a-tabs :active-key="activeFlavor" size="small" class="strategy-tabs" animation @change="onFlavorTabChange">
            <a-tab-pane v-for="profile in strategyProfiles" :key="profile.key" :title="profile.label">
              <div class="capability-band">
                <div class="profile-heading compact">
                  <div class="profile-desc">{{ profile.description }}</div>
                  <a-tooltip :content="profile.reason">
                    <span class="profile-debug">plan</span>
                  </a-tooltip>
                </div>
                <div class="capability-list">
                  <div v-for="item in activeCapabilities" :key="item.key" class="capability-chip" :class="{ off: !item.enabled }">
                    <span class="status-dot" />
                    <span>{{ item.label }}</span>
                    <small>{{ item.enabled ? '开启' : '关闭' }}</small>
                  </div>
                </div>
              </div>

              <div class="metric-strip">
                <div v-for="item in activeBudget" :key="item.label" class="metric-item">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>

              <section class="settings-section">
                <div v-if="activeControls.length" class="compact-section-title">可调预算</div>
                <div v-if="activeControls.length" class="parameter-grid">
                  <label v-for="control in activeControls" :key="control.key" class="parameter-field">
                    <span>{{ control.label }}</span>
                    <a-input-number
                      v-model="form[control.key]"
                      :min="control.min"
                      :max="control.max"
                      :disabled="!authStore.isAdmin"
                    />
                  </label>
                </div>
                <div v-else class="fixed-note">该策略的检索预算固定为上方显示值。</div>
              </section>
            </a-tab-pane>
          </a-tabs>

          <details class="global-weights">
            <summary>
              <span>全局权重</span>
              <small>影响底层检索与重排，不按策略单独区分</small>
            </summary>
            <div class="weight-grid">
              <label class="compact-slider">
                <span>语义权重 {{ form.denseWeight.toFixed(2) }}</span>
                <a-slider v-model="form.denseWeight" :min="0" :max="1" :step="0.05" :disabled="!authStore.isAdmin" />
              </label>
              <label class="compact-slider">
                <span>关键词权重 {{ form.sparseWeight.toFixed(2) }}</span>
                <a-slider v-model="form.sparseWeight" :min="0" :max="1" :step="0.05" :disabled="!authStore.isAdmin" />
              </label>
              <label class="compact-slider">
                <span>LLM 重排权重 {{ form.rerankLlmWeight.toFixed(2) }}</span>
                <a-slider v-model="form.rerankLlmWeight" :min="0" :max="1" :step="0.05" :disabled="!authStore.isAdmin" />
              </label>
              <label class="compact-slider">
                <span>RRF 权重 {{ form.rerankRrfWeight.toFixed(2) }}</span>
                <a-slider v-model="form.rerankRrfWeight" :min="0" :max="1" :step="0.05" :disabled="!authStore.isAdmin" />
              </label>
            </div>
          </details>

          <div class="settings-actions">
            <a-button type="primary" :loading="saving" :disabled="!authStore.isAdmin" @click="saveRetrievalSettings">
              保存策略微调
            </a-button>
            <a-button :loading="loading" @click="loadSettings">恢复当前值</a-button>
          </div>
        </a-tab-pane>

        <a-tab-pane key="security" title="安全">
          <section class="settings-section">
            <div class="section-heading">
              <div>
                <div class="section-title">访问令牌</div>
                <div class="section-hint">更新后立即写入本地请求 Token，并调用后端持久化。</div>
              </div>
              <span class="section-kicker">Admin</span>
            </div>
            <div class="token-row">
              <a-input-password
                v-model="form.token"
                placeholder="输入新的访问令牌"
                allow-clear
                :disabled="!authStore.isAdmin"
              />
              <a-button type="primary" :loading="tokenSaving" :disabled="!authStore.isAdmin" @click="saveToken">
                更新
              </a-button>
            </div>
          </section>
        </a-tab-pane>
      </a-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { getSettings, updateSettings, updateToken } from '../../api/settings'
import { getRuntimeInfo, type RuntimeInfo } from '../../api/system'
import { useAuthStore } from '../../stores/auth'

type FlavorKey = 'balanced' | 'exact' | 'recall' | 'discovery'
type FormNumberKey =
  | 'searchLimit'
  | 'hydeLimit'
  | 'rrfMaxResults'
  | 'rerankMaxTopK'
  | 'queryExpansionCount'
  | 'multiHopMaxDiscovered'

interface BudgetControl {
  key: FormNumberKey
  label: string
  min: number
  max: number
  flavors: FlavorKey[]
}

interface CapabilityStatus {
  key: string
  label: string
  enabled: boolean
}

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const tokenSaving = ref(false)
const rawSettings = ref<Record<string, string>>({})
const runtimeInfo = ref<RuntimeInfo | null>(null)
const loadError = ref('')
const loadedAt = ref('')
const activeFlavor = ref<FlavorKey>('balanced')

const form = reactive<Record<string, any>>({
  token: '',
  retrievalFlavor: 'balanced',
  searchLimit: 10,
  hydeLimit: 10,
  rrfMaxResults: 20,
  rerankMaxTopK: 10,
  queryExpansionCount: 3,
  multiHopMaxDiscovered: 5,
  contextExpandWindow: 1,
  contextExpandMaxChars: 2400,
  denseWeight: 0.8,
  sparseWeight: 0.2,
  rerankLlmWeight: 0.7,
  rerankRrfWeight: 0.3,
  useEntityConfirm: true,
  useRewrite: true,
  useHyde: true,
  useQueryExpansion: true,
  useTableExpand: true,
  useContextExpand: true,
  useRerank: true,
  useGroundedness: false,
  useMultiHop: false,
})

const strategyProfiles: Array<{ key: FlavorKey; label: string; description: string; reason: string }> = [
  {
    key: 'balanced',
    label: '标准问答',
    description: '默认问答路径，使用主检索 + HyDE + RRF + 重排，适合大多数问题。',
    reason: 'balanced_current_defaults',
  },
  {
    key: 'exact',
    label: '精确查找',
    description: '固定小预算，关闭 HyDE、扩展查询和回退，优先减少误召回。',
    reason: 'exact_precision',
  },
  {
    key: 'recall',
    label: '全面查找',
    description: '固定大预算，使用扩展查询并行召回，适合模糊、同义表达问题。',
    reason: 'recall_high_coverage',
  },
  {
    key: 'discovery',
    label: '关联查找',
    description: '多跳发现路径，先找相关实体，再围绕发现实体继续检索。',
    reason: 'discovery_current_path',
  },
]

const budgetControls: BudgetControl[] = [
  { key: 'searchLimit', label: '主检索候选', min: 1, max: 50, flavors: ['balanced', 'discovery'] },
  { key: 'hydeLimit', label: 'HyDE 候选', min: 1, max: 50, flavors: ['balanced'] },
  { key: 'rrfMaxResults', label: '融合结果上限', min: 1, max: 50, flavors: ['balanced', 'discovery'] },
  { key: 'rerankMaxTopK', label: '重排/最终上下文上限', min: 1, max: 30, flavors: ['balanced', 'discovery'] },
  { key: 'queryExpansionCount', label: '扩展查询数量', min: 2, max: 4, flavors: ['recall'] },
  { key: 'multiHopMaxDiscovered', label: '多跳发现实体上限', min: 1, max: 10, flavors: ['discovery'] },
]

const settingsCount = computed(() => Object.keys(rawSettings.value).length)
const embeddingLabel = computed(() => {
  const info = runtimeInfo.value
  if (!info) return '未读取'
  return `${info.embedding_model} / ${info.embedding_dim}d / ${info.embedding_device}`
})
const backendMilvusLabel = computed(() => {
  const uri = runtimeInfo.value?.milvus_uri || ''
  return uri ? `Milvus / ${uri}` : '未读取'
})
const hostMilvusUri = computed(() => {
  const uri = runtimeInfo.value?.milvus_uri || ''
  if (!uri) return '未读取'
  return uri.includes('milvus-standalone') ? 'http://localhost:19530' : uri
})
const backendDatabaseLabel = computed(() => {
  const path = runtimeInfo.value?.database_path || ''
  if (!path) return '未读取'
  const normalized = path === './data/app.db' ? '/app/data/app.db' : path
  return `SQLite / ${normalized}`
})
const activeControls = computed(() =>
  budgetControls.filter((control) => control.flavors.includes(activeFlavor.value)),
)
const activeBudget = computed(() => buildBudget(activeFlavor.value))
const activeCapabilities = computed(() => buildCapabilities(activeFlavor.value))
const tokenStatus = computed(() => {
  const token = localStorage.getItem('api_token') || ''
  return token ? '已配置' : '未配置'
})

function onFlavorTabChange(key: string | number) {
  if (['balanced', 'exact', 'recall', 'discovery'].includes(String(key))) {
    activeFlavor.value = String(key) as FlavorKey
  }
}

async function loadSettings() {
  loading.value = true
  loadError.value = ''
  try {
    if (!authStore.currentUser) {
      await authStore.fetchMe()
    }
    const [settingsData, info] = await Promise.all([
      getSettings(),
      getRuntimeInfo(),
    ])
    rawSettings.value = settingsData
    runtimeInfo.value = info
    applySettings(settingsData)
    loadedAt.value = new Date().toLocaleString()
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || '设置加载失败'
    Message.error(loadError.value)
  } finally {
    loading.value = false
  }
}

function applySettings(data: Record<string, string>) {
  form.token = ''
  form.retrievalFlavor = readString(data, 'query.retrieval_flavor', 'balanced')
  form.searchLimit = readNumber(data, 'query.search_limit', 10)
  form.hydeLimit = readNumber(data, 'query.hyde_limit', 10)
  form.rrfMaxResults = readNumber(data, 'query.rrf_max_results', 20)
  form.rerankMaxTopK = readNumber(data, 'query.rerank_max_top_k', 10)
  form.queryExpansionCount = readNumber(data, 'query.query_expansion_count', 3)
  form.multiHopMaxDiscovered = readNumber(data, 'query.multi_hop_max_discovered', 5)
  form.contextExpandWindow = readNumber(data, 'query.context_expand_window', 1)
  form.contextExpandMaxChars = readNumber(data, 'query.context_expand_max_chars', 2400)
  form.denseWeight = readNumber(data, 'query.dense_weight', 0.8)
  form.sparseWeight = readNumber(data, 'query.sparse_weight', 0.2)
  form.rerankLlmWeight = readNumber(data, 'query.rerank_llm_weight', 0.7)
  form.rerankRrfWeight = readNumber(data, 'query.rerank_rrf_weight', 0.3)
  form.useEntityConfirm = readBool(data, 'query.use_entity_confirm', true)
  form.useRewrite = readBool(data, 'query.use_rewrite', true)
  form.useHyde = readBool(data, 'query.use_hyde', true)
  form.useQueryExpansion = readBool(data, 'query.use_query_expansion', true)
  form.useTableExpand = readBool(data, 'query.use_table_expand', true)
  form.useContextExpand = readBool(data, 'query.use_context_expand', true)
  form.useRerank = readBool(data, 'query.use_rerank', true)
  form.useGroundedness = readBool(data, 'query.use_groundedness', false)
  form.useMultiHop = readBool(data, 'query.use_multi_hop', false)
}

async function saveRetrievalSettings() {
  if (!authStore.isAdmin) return
  saving.value = true
  try {
    const updates: Record<string, string> = {
      'query.retrieval_flavor': form.retrievalFlavor,
      'query.search_limit': String(form.searchLimit),
      'query.hyde_limit': String(form.hydeLimit),
      'query.rrf_max_results': String(form.rrfMaxResults),
      'query.rerank_max_top_k': String(form.rerankMaxTopK),
      'query.query_expansion_count': String(form.queryExpansionCount),
      'query.multi_hop_max_discovered': String(form.multiHopMaxDiscovered),
      'query.context_expand_window': String(form.contextExpandWindow),
      'query.context_expand_max_chars': String(form.contextExpandMaxChars),
      'query.dense_weight': String(form.denseWeight),
      'query.sparse_weight': String(form.sparseWeight),
      'query.rerank_llm_weight': String(form.rerankLlmWeight),
      'query.rerank_rrf_weight': String(form.rerankRrfWeight),
    }
    rawSettings.value = await updateSettings(updates)
    applySettings(rawSettings.value)
    loadedAt.value = new Date().toLocaleString()
    Message.success('策略微调已保存')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveToken() {
  if (!authStore.isAdmin) return
  const token = String(form.token || '').trim()
  if (!token) return
  tokenSaving.value = true
  try {
    await updateToken(token)
    localStorage.setItem('api_token', token)
    form.token = ''
    Message.success('Token 已更新')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || 'Token 更新失败')
  } finally {
    tokenSaving.value = false
  }
}

function buildBudget(flavor: FlavorKey): Array<{ label: string; value: string; note: string }> {
  if (flavor === 'exact') {
    return budgetRows({
      search: 8,
      hyde: 0,
      rrf: 8,
      candidates: 8,
      final: 3,
      chars: 5000,
      perEntity: 3,
    }, '固定')
  }
  if (flavor === 'recall') {
    return budgetRows({
      search: 20,
      hyde: 0,
      rrf: 40,
      candidates: 30,
      final: 8,
      chars: 14000,
      perEntity: 8,
    }, `扩展查询 ${form.queryExpansionCount} 条`)
  }
  if (flavor === 'discovery') {
    return budgetRows({
      search: form.searchLimit,
      hyde: 0,
      rrf: form.rrfMaxResults,
      candidates: form.rerankMaxTopK,
      final: form.rerankMaxTopK,
      chars: 8000,
      perEntity: 5,
    }, `发现实体上限 ${form.multiHopMaxDiscovered}`)
  }
  return budgetRows({
    search: form.searchLimit,
    hyde: form.hydeLimit,
    rrf: form.rrfMaxResults,
    candidates: form.rerankMaxTopK,
    final: form.rerankMaxTopK,
    chars: 8000,
    perEntity: 5,
  }, '读取全局默认')
}

function budgetRows(
  budget: { search: number; hyde: number; rrf: number; candidates: number; final: number; chars: number; perEntity: number },
  note: string,
) {
  return [
    { label: '主检索', value: String(budget.search), note },
    { label: 'HyDE', value: String(budget.hyde), note: budget.hyde ? note : '不使用' },
    { label: '融合', value: String(budget.rrf), note },
    { label: '重排候选', value: String(budget.candidates), note },
    { label: '最终上下文', value: String(budget.final), note },
    { label: '上下文字符', value: budget.chars.toLocaleString(), note },
    { label: '单实体保底', value: String(budget.perEntity), note },
  ]
}

function buildCapabilities(flavor: FlavorKey): CapabilityStatus[] {
  const common = [
    { key: 'entity', label: '实体识别', enabled: Boolean(form.useEntityConfirm) },
    { key: 'rewrite', label: '问题改写', enabled: Boolean(form.useRewrite) },
  ]
  const finishing = [
    { key: 'table', label: '表格扩展', enabled: Boolean(form.useTableExpand) },
    { key: 'context', label: '补充上下文', enabled: Boolean(form.useContextExpand) },
    { key: 'rerank', label: '相关性重排', enabled: Boolean(form.useRerank) },
  ]

  if (flavor === 'exact') {
    return [...common, ...finishing]
  }
  if (flavor === 'recall') {
    return [
      ...common,
      { key: 'expansion', label: '换几种说法查找', enabled: Boolean(form.useQueryExpansion) },
      ...finishing,
    ]
  }
  if (flavor === 'discovery') {
    return [
      ...common,
      { key: 'multiHop', label: '多跳发现', enabled: true },
      ...finishing,
    ]
  }
  return [
    ...common,
    { key: 'hyde', label: '假设文档', enabled: Boolean(form.useHyde) },
    ...finishing,
  ]
}

function readString(data: Record<string, string>, key: string, fallback: string): string {
  return data[key] || fallback
}

function readNumber(data: Record<string, string>, key: string, fallback: number): number {
  const value = Number(data[key])
  return Number.isFinite(value) ? value : fallback
}

function readBool(data: Record<string, string>, key: string, fallback: boolean): boolean {
  const value = data[key]
  if (value === undefined || value === '') return fallback
  return ['true', '1', 'yes', 'on'].includes(value.toLowerCase())
}

onMounted(loadSettings)
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
  padding: 14px 18px 18px;
}

.settings-tabs :deep(.arco-tabs-nav-tab),
.strategy-tabs :deep(.arco-tabs-nav-tab) {
  padding-left: 0;
}

.settings-tabs :deep(.arco-tabs-nav-tab-list),
.strategy-tabs :deep(.arco-tabs-nav-tab-list) {
  padding-left: 0;
}

.settings-tabs :deep(.arco-tabs-nav-type-line .arco-tabs-tab:first-of-type),
.strategy-tabs :deep(.arco-tabs-nav-type-line .arco-tabs-tab:first-of-type) {
  margin-left: 0 !important;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.status-card,
.info-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fbfdff;
}

.status-card {
  display: grid;
  gap: 6px;
  padding: 14px;
}

.status-label,
.status-card small,
.metric-item span,
.info-row span,
.section-hint,
.profile-desc {
  color: var(--text-muted);
  font-size: 12px;
}

.status-card strong,
.metric-item strong {
  color: var(--text-primary);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.status-card strong.ok {
  color: #166534;
}

.status-card strong.bad {
  color: #991b1b;
}

.info-panel {
  margin-top: 14px;
  padding: 14px;
}

.panel-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

.info-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 18px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.info-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.readonly-note,
.fixed-note {
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: 12px;
}

.readonly-note {
  margin-bottom: 12px;
  color: #7c2d12;
  background: #fff7ed;
  border: 1px solid #fed7aa;
}

.fixed-note {
  color: var(--text-secondary);
  background: #f8fafc;
  border: 1px solid var(--border);
}

.strategy-note {
  margin: 4px 0 10px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.settings-section {
  margin-bottom: 0;
}

.compact-section-title {
  margin: 2px 0 8px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.capability-band {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.profile-heading.compact {
  margin-bottom: 7px;
}

.section-heading,
.profile-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.section-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.section-hint,
.profile-desc {
  margin-top: 4px;
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

.profile-debug {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 11px;
  cursor: help;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(7, minmax(88px, 1fr));
  gap: 6px;
  margin-bottom: 10px;
}

.metric-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fbfdff;
}

.metric-item span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parameter-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
}

.parameter-field,
.compact-slider {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.parameter-field {
  display: grid;
  grid-template-columns: max-content 86px;
  width: max-content;
  min-width: 210px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fbfdff;
}

.parameter-field span {
  white-space: nowrap;
}

.parameter-field :deep(.arco-input-number) {
  width: 86px;
}

.compact-slider span {
  flex: 0 0 138px;
  white-space: nowrap;
}

.compact-slider :deep(.arco-slider) {
  flex: 1;
  min-width: 120px;
}

.capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
}

.capability-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 3px 8px;
  border: 1px solid #bbf7d0;
  border-radius: 999px;
  background: #f0fdf4;
  color: var(--text-secondary);
  font-size: 12px;
}

.capability-chip.off {
  border-color: var(--border);
  background: var(--bg-hover);
  color: var(--text-muted);
}

.capability-chip small {
  color: #166534;
  font-size: 11px;
}

.capability-chip.off small {
  color: var(--text-muted);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #22c55e;
}

.capability-chip.off .status-dot {
  background: #cbd5e1;
}

.global-weights {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.global-weights summary {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  list-style: none;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.global-weights summary::-webkit-details-marker {
  display: none;
}

.global-weights summary small {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}

.global-weights summary::after {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
  content: '展开';
}

.global-weights[open] summary::after {
  content: '收起';
}

.weight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 8px 18px;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fbfdff;
}

.token-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.settings-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .status-grid,
  .metric-strip,
  .weight-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .settings-card {
    padding: 14px;
  }

  .section-heading,
  .profile-heading {
    flex-direction: column;
  }

  .status-grid,
  .metric-strip,
  .info-list,
  .weight-grid,
  .token-row {
    grid-template-columns: 1fr;
  }

  .parameter-field,
  .compact-slider {
    align-items: stretch;
    flex-direction: column;
  }

  .parameter-field span,
  .compact-slider span {
    flex: none;
  }

  .parameter-field,
  .parameter-field :deep(.arco-input-number) {
    width: 100%;
  }
}
</style>
