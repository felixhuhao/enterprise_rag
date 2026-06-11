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
          <SystemStatusPanel
            :load-error="loadError"
            :username="authStore.currentUser?.username || ''"
            :user-id="authStore.currentUser?.user_id || ''"
            :is-admin="authStore.isAdmin"
            :settings-count="settingsCount"
            :loaded-at="loadedAt"
            :chat-model="runtimeInfo?.chat_model || ''"
            :embedding-label="embeddingLabel"
            :backend-milvus-label="backendMilvusLabel"
            :host-milvus-uri="hostMilvusUri"
            :backend-database-label="backendDatabaseLabel"
            :token-status="tokenStatus"
          />
          <RecentJobsPanel
            v-if="authStore.isAdmin"
            :jobs="recentJobs"
            :loading="jobsLoading"
            :error="jobsError"
            @refresh="loadRecentJobs"
          />
        </a-tab-pane>

        <a-tab-pane key="tuning" title="策略微调">
          <StrategyTuningPanel
            v-model:active-flavor="activeFlavor"
            :is-admin="authStore.isAdmin"
            :strategy-profiles="strategyProfiles"
            :active-capabilities="activeCapabilities"
            :active-budget="activeBudget"
            :active-controls="activeControls"
            :form="form"
            :saving="saving"
            :loading="loading"
            @update-form-value="setFormValue"
            @save="saveRetrievalSettings"
            @reload="loadSettings"
          />
        </a-tab-pane>

        <a-tab-pane key="security" title="安全">
          <TokenSettingsPanel
            v-model="form.token"
            :is-admin="authStore.isAdmin"
            :saving="tokenSaving"
            @save="saveToken"
          />
        </a-tab-pane>

        <a-tab-pane v-if="isTagGovernanceEnabled" key="tags" title="标签治理">
          <TagGovernancePanel
            v-model:preview-document-id="previewDocumentId"
            v-model:preview-section-title="previewSectionTitle"
            v-model:preview-text="previewText"
            v-model:tag-editor-open="tagEditorOpen"
            v-model:tag-label="tagForm.label"
            v-model:tag-description="tagForm.description"
            v-model:tag-enabled="tagForm.enabled"
            v-model:tag-ui-visible="tagForm.uiVisible"
            :is-admin="authStore.isAdmin"
            :tag-metrics-loading="tagMetricsLoading"
            :tag-metrics="tagMetrics"
            :preview-docs-loading="previewDocsLoading"
            :preview-loading="previewLoading"
            :preview-documents="previewDocuments"
            :preview-result="previewResult"
            :tag-loading="tagLoading"
            :tag-records="tagRecords"
            :selected-tag="selectedTag"
            :tag-saving="tagSaving"
            @run-preview="runTagPreview"
            @clear-preview="clearTagPreview"
            @open-editor="openTagEditor"
            @reset-tag="resetTag"
            @save-editor="saveTagEditor"
          />
        </a-tab-pane>
      </a-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { listJobs, type JobRecord } from '../../api/adminJobs'
import { listDocuments, type Document } from '../../api/documents'
import { getSettings, updateSettings, updateToken } from '../../api/settings'
import { getRuntimeInfo, type RuntimeInfo } from '../../api/system'
import {
  getStructuredTagMetrics,
  listStructuredTags,
  previewStructuredTags,
  resetStructuredTag,
  updateStructuredTag,
  type StructuredTagMetrics,
  type StructuredTagPreviewResponse,
  type StructuredTagRecord,
} from '../../api/structuredTags'
import { useAuthStore } from '../../stores/auth'
import StrategyTuningPanel from './StrategyTuningPanel.vue'
import RecentJobsPanel from './RecentJobsPanel.vue'
import SystemStatusPanel from './SystemStatusPanel.vue'
import TagGovernancePanel from './TagGovernancePanel.vue'
import TokenSettingsPanel from './TokenSettingsPanel.vue'

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
const isTagGovernanceEnabled = import.meta.env.VITE_ENABLE_TAG_GOVERNANCE === 'true'
const loading = ref(false)
const saving = ref(false)
const tokenSaving = ref(false)
const rawSettings = ref<Record<string, string>>({})
const runtimeInfo = ref<RuntimeInfo | null>(null)
const loadError = ref('')
const loadedAt = ref('')
const activeFlavor = ref<FlavorKey>('balanced')
const tagLoading = ref(false)
const tagMetricsLoading = ref(false)
const tagSaving = ref(false)
const jobsLoading = ref(false)
const tagRecords = ref<StructuredTagRecord[]>([])
const tagMetrics = ref<StructuredTagMetrics | null>(null)
const recentJobs = ref<JobRecord[]>([])
const jobsError = ref('')
const selectedTag = ref<StructuredTagRecord | null>(null)
const tagEditorOpen = ref(false)
const previewDocsLoading = ref(false)
const previewLoading = ref(false)
const allDocuments = ref<Document[]>([])
const previewDocumentId = ref('')
const previewSectionTitle = ref('')
const previewText = ref('')
const previewResult = ref<StructuredTagPreviewResponse | null>(null)

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

const tagForm = reactive({
  label: '',
  description: '',
  enabled: true,
  uiVisible: true,
})

const strategyProfiles: Array<{ key: FlavorKey; label: string; description: string; reason: string }> = [
  {
    key: 'balanced',
    label: '标准问答',
    description: '默认问答路径，使用主检索 + 语义扩展 + RRF + 重排，适合大多数问题。',
    reason: 'balanced_current_defaults',
  },
  {
    key: 'exact',
    label: '精确查找',
    description: '固定小预算，关闭语义扩展、扩展查询和回退，优先减少误召回。',
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
  { key: 'hydeLimit', label: '语义扩展候选', min: 1, max: 50, flavors: ['balanced'] },
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
const previewDocuments = computed(() => allDocuments.value.filter((doc) => doc.status === 'completed'))
const tokenStatus = computed(() => {
  const token = localStorage.getItem('api_token') || ''
  return token ? '已配置' : '未配置'
})

function setFormValue(key: string, value: unknown) {
  form[key] = value
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
    if (authStore.isAdmin) {
      await Promise.all([
        ...(isTagGovernanceEnabled
          ? [
              loadTagRecords(),
              loadTagMetrics(),
              loadPreviewDocuments(),
            ]
          : []),
        loadRecentJobs(),
      ])
    }
    loadedAt.value = new Date().toLocaleString()
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || '设置加载失败'
    Message.error(loadError.value)
  } finally {
    loading.value = false
  }
}

async function loadTagRecords() {
  if (!authStore.isAdmin || !isTagGovernanceEnabled) return
  tagLoading.value = true
  try {
    const data = await listStructuredTags()
    tagRecords.value = data.records
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '标签加载失败')
  } finally {
    tagLoading.value = false
  }
}

async function loadTagMetrics() {
  if (!authStore.isAdmin || !isTagGovernanceEnabled) return
  tagMetricsLoading.value = true
  try {
    tagMetrics.value = await getStructuredTagMetrics()
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '标签统计加载失败')
  } finally {
    tagMetricsLoading.value = false
  }
}

async function loadPreviewDocuments() {
  if (!authStore.isAdmin || !isTagGovernanceEnabled) return
  previewDocsLoading.value = true
  try {
    allDocuments.value = await listDocuments()
  } catch {
    allDocuments.value = []
  } finally {
    previewDocsLoading.value = false
  }
}

async function loadRecentJobs() {
  if (!authStore.currentUser) {
    await authStore.fetchMe()
  }
  if (!authStore.isAdmin) return
  jobsLoading.value = true
  jobsError.value = ''
  try {
    const data = await listJobs({ limit: 12 })
    recentJobs.value = data.jobs
  } catch (e: any) {
    jobsError.value = e?.response?.data?.detail || '后台任务加载失败'
  } finally {
    jobsLoading.value = false
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

function openTagEditor(record: StructuredTagRecord) {
  if (!isTagGovernanceEnabled) return
  selectedTag.value = record
  tagForm.label = record.label
  tagForm.description = record.description
  tagForm.enabled = record.enabled
  tagForm.uiVisible = record.ui_visible
  tagEditorOpen.value = true
}

async function saveTagEditor() {
  if (!isTagGovernanceEnabled) return
  if (!selectedTag.value) return
  const label = tagForm.label.trim()
  if (!label) {
    Message.warning('显示名称不能为空')
    return
  }
  tagSaving.value = true
  try {
    const result = await updateStructuredTag(selectedTag.value.tag_key, {
      label,
      description: tagForm.description.trim(),
      enabled: tagForm.enabled,
      ui_visible: tagForm.uiVisible,
    })
    tagEditorOpen.value = false
    Message.success('标签设置已保存')
    if (result.reindex_required) {
      Message.warning('启用状态变化会影响入库结果；已有索引需重建后完全一致')
    }
    await loadTagRecords()
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    tagSaving.value = false
  }
}

async function resetTag(record: StructuredTagRecord) {
  if (!isTagGovernanceEnabled) return
  try {
    const result = await resetStructuredTag(record.tag_key)
    Message.success('已恢复内置默认值')
    if (result.reindex_required) {
      Message.warning('启用状态变化会影响入库结果；已有索引需重建后完全一致')
    }
    await loadTagRecords()
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '重置失败')
  }
}

async function runTagPreview() {
  if (!isTagGovernanceEnabled) return
  const documentId = previewDocumentId.value
  const text = previewText.value.trim()
  if (!documentId && !text) {
    Message.warning('请选择文档或输入预览文本')
    return
  }
  previewLoading.value = true
  try {
    previewResult.value = await previewStructuredTags({
      document_id: documentId || undefined,
      text: documentId ? undefined : text,
      section_title: previewSectionTitle.value.trim() || undefined,
      max_chunks: 20,
    })
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '预览失败')
  } finally {
    previewLoading.value = false
  }
}

function clearTagPreview() {
  if (!isTagGovernanceEnabled) return
  previewDocumentId.value = ''
  previewSectionTitle.value = ''
  previewText.value = ''
  previewResult.value = null
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
    { label: '语义扩展', value: String(budget.hyde), note: budget.hyde ? note : '不使用' },
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
      { key: 'expansion', label: '扩展查询', enabled: Boolean(form.useQueryExpansion) },
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
    { key: 'hyde', label: '语义扩展', enabled: Boolean(form.useHyde) },
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
.settings-tabs :deep(.arco-tabs-nav-tab-list),
.settings-tabs :deep(.arco-tabs-nav-tab-list) {
  padding-left: 0;
}

.settings-tabs :deep(.arco-tabs-nav-type-line .arco-tabs-tab:first-of-type) {
  margin-left: 0 !important;
}

@media (max-width: 760px) {
  .settings-card {
    padding: 14px;
  }
}
</style>
