<template>
  <div :ref="setRecordsTableContainer" class="records-card">
    <div class="records-head">
      <div class="records-title">检索记录</div>
      <div class="records-actions">
        <a-button size="mini" @click="recordColumns.resetColumnWidths()">重置列宽</a-button>
        <a-select
          :model-value="flavorFilter"
          :style="{ width: '150px' }"
          size="small"
          placeholder="策略"
          allow-clear
          @change="onFlavorChange"
        >
          <a-option value="">全部策略</a-option>
          <a-option v-for="mode in FLAVOR_OPTIONS" :key="mode.id" :value="mode.id">
            {{ mode.name }}
          </a-option>
        </a-select>
      </div>
    </div>

    <a-table
      :data="records"
      :pagination="{ current: currentPage, total, pageSize: 15, showTotal: true }"
      row-key="id"
      class="records-table"
      column-resizable
      @column-resize="recordColumns.onColumnResize"
      @page-change="onPageChange"
    >
      <template #columns>
        <a-table-column title="时间" data-index="created_at" :width="recordColumns.columnWidth('created_at')">
          <template #cell="{ record }">
            <span class="time-cell">{{ formatTime(record.created_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column title="问题" data-index="query" :width="recordColumns.columnWidth('query')" :ellipsis="true">
          <template #cell="{ record }">
            <span class="query-cell" :title="record.query">{{ record.query }}</span>
          </template>
        </a-table-column>
        <a-table-column title="状态" data-index="status" :width="recordColumns.columnWidth('status')">
          <template #cell="{ record }">
            <span class="status-tag" :class="statusClass(record.status)" :title="record.error_code || undefined">
              {{ statusLabel(record.status) }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="策略" data-index="retrieval_flavor" :width="recordColumns.columnWidth('retrieval_flavor')">
          <template #cell="{ record }">
            <span class="flavor-tag" :class="'flavor-' + flavorValue(record)">
              {{ flavorLabel(record.retrieval_flavor) }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="仅资料" data-index="strict_evidence" :width="recordColumns.columnWidth('strict_evidence')" align="center">
          <template #cell="{ record }">
            <span class="strict-tag" :class="{ on: !!record.strict_evidence }">
              {{ record.strict_evidence ? '是' : '否' }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="结果" data-index="result_count" :width="recordColumns.columnWidth('result_count')" />
        <a-table-column title="相关性重排" data-index="rerank_avg_score" :width="recordColumns.columnWidth('rerank_avg_score')">
          <template #cell="{ record }">
            <span class="quality-cell">{{ formatRerank(record.rerank_avg_score) }}</span>
          </template>
        </a-table-column>
        <a-table-column title="耗时" data-index="total_ms" :width="recordColumns.columnWidth('total_ms')">
          <template #cell="{ record }">
            <span v-if="record.total_ms" class="time-ms" :title="timingTitle(record)">
              {{ formatMs(record.total_ms) }}
            </span>
            <span v-else class="time-dash">-</span>
          </template>
        </a-table-column>
        <a-table-column data-index="details" :width="recordColumns.columnWidth('details')" align="center">
          <template #title>
            <span class="resize-title center">
              详情
              <span class="manual-resize-handle" @mousedown="recordColumns.startResize('details', $event)" />
            </span>
          </template>
          <template #cell="{ record }">
            <button class="details-btn" @click="openDetail(record)">查看</button>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <a-empty description="暂无检索统计，进行查询后将自动收集" />
      </template>
    </a-table>

    <a-drawer
      :visible="drawerOpen"
      width="min(1280px, 94vw)"
      title="查询详情"
      :footer="false"
      @cancel="drawerOpen = false"
    >
      <a-spin :loading="drawerLoading" style="width: 100%">
        <div v-if="drawerRecord" class="detail-content">
          <section class="detail-section">
            <div class="section-title">运行概览</div>
            <div class="run-summary">
              <span>状态：{{ statusLabel(drawerRecord.status) }}</span>
              <span v-if="drawerRecord.error_code">错误：{{ drawerRecord.error_code }}</span>
              <span>策略：{{ flavorLabel(drawerRecord.retrieval_flavor) }}</span>
              <span>仅基于资料回答：{{ drawerRecord.strict_evidence ? '是' : '否' }}</span>
              <span>主检索：{{ searchModeLabel(drawerRecord.search_mode) }}</span>
              <span>语义扩展：{{ searchModeLabel(drawerRecord.search_mode_hyde) }}</span>
              <span v-if="drawerRecord.endpoint">入口：{{ endpointLabel(drawerRecord.endpoint) }}</span>
              <span v-if="drawerRecord.model">模型：{{ drawerRecord.model }}</span>
              <span v-if="drawerRecord.total_ms">总耗时：{{ formatMs(drawerRecord.total_ms) }}</span>
              <span v-if="slowestStageLabel">最慢阶段：{{ slowestStageLabel }}</span>
            </div>
          </section>

          <section v-if="timingPairs.length" class="detail-section">
            <div class="section-title">阶段耗时</div>
            <div class="timing-list">
              <div
                v-for="pair in timingPairs"
                :key="pair.key"
                class="timing-row"
                :class="{ slowest: isSlowestTiming(pair.key) }"
              >
                <span class="timing-label">{{ pair.label }}</span>
                <span class="timing-track">
                  <span class="timing-bar" :style="timingBarStyle(pair.ms)" />
                </span>
                <span class="timing-value">{{ formatMs(pair.ms) }}</span>
                <span v-if="isSlowestTiming(pair.key)" class="slowest-badge">最慢</span>
              </div>
            </div>
          </section>

          <div class="detail-grid">
            <section v-if="settingPairs.length" class="detail-section">
              <div class="section-title">实际设置</div>
              <dl class="kv-grid">
                <template v-for="pair in settingPairs" :key="pair.key">
                  <dt>{{ pair.label }}</dt>
                  <dd :title="pair.value">{{ pair.value }}</dd>
                </template>
              </dl>
            </section>

            <section v-if="resultShapePairs.length" class="detail-section">
              <div class="section-title">结果形状</div>
              <dl class="kv-grid">
                <template v-for="pair in resultShapePairs" :key="pair.key">
                  <dt>{{ pair.label }}</dt>
                  <dd :title="pair.value">{{ pair.value }}</dd>
                </template>
              </dl>
            </section>

            <section v-if="fallbackPairs.length" class="detail-section">
              <div class="section-title">Fallback</div>
              <dl class="kv-grid">
                <template v-for="pair in fallbackPairs" :key="pair.key">
                  <dt>{{ pair.label }}</dt>
                  <dd :title="pair.value">{{ pair.value }}</dd>
                </template>
              </dl>
            </section>

            <section v-if="tokenPairs.length" class="detail-section">
              <div class="section-title">Token</div>
              <dl class="kv-grid">
                <template v-for="pair in tokenPairs" :key="pair.key">
                  <dt>{{ pair.label }}</dt>
                  <dd :title="pair.value">{{ pair.value }}</dd>
                </template>
              </dl>
            </section>
          </div>

          <section v-if="citationRows.length" class="detail-section">
            <div class="section-title">引用</div>
            <div class="citation-list">
              <div v-for="(citation, index) in citationRows" :key="citationKey(citation, index)" class="citation-row">
                <span class="citation-id">{{ citationId(citation, index) }}</span>
                <span class="citation-title" :title="citationTitle(citation)">{{ citationTitle(citation) }}</span>
                <span class="citation-meta" :title="citationMeta(citation)">{{ citationMeta(citation) }}</span>
              </div>
            </div>
          </section>

          <section class="detail-section">
            <div class="section-title">检索结果</div>
            <div v-if="drawerError" class="drawer-error">{{ drawerError }}</div>
            <div v-else-if="!drawerChunks.length" class="drawer-empty">暂无命中记录</div>
            <div v-else :ref="setDrawerTableContainer" class="drawer-table-wrap">
              <a-table
                :data="drawerChunks"
                :pagination="{ pageSize: 20, size: 'small' }"
                row-key="rank"
                size="small"
                column-resizable
                @column-resize="drawerColumns.onColumnResize"
              >
                <template #columns>
                  <a-table-column title="#" data-index="rank" :width="drawerColumns.columnWidth('rank')" />
                  <a-table-column title="命中信息" data-index="hit" :width="drawerColumns.columnWidth('hit')">
                    <template #cell="{ record }">
                      <div class="hit-summary">
                        <div class="hit-title" :title="displayFileTitle(record)">
                          {{ displayFileTitle(record) }}
                        </div>
                        <div class="hit-meta">
                          <span class="meta-pill" :title="formatLocation(record)">
                            {{ formatLocation(record) }}
                          </span>
                          <span v-if="record.entity_name" class="meta-pill" :title="record.entity_name">
                            实体：{{ record.entity_name }}
                          </span>
                        </div>
                      </div>
                    </template>
                  </a-table-column>
                  <a-table-column title="召回路径" data-index="path" :width="drawerColumns.columnWidth('path')">
                    <template #cell="{ record }">
                      <span class="path-cell" :title="formatPath(record)">{{ formatPath(record) }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column title="分数" data-index="score" :width="drawerColumns.columnWidth('score')">
                    <template #cell="{ record }">
                      <span class="score-cell">{{ formatScore(record.score) }}</span>
                    </template>
                  </a-table-column>
                  <a-table-column title="标签" data-index="tags" :width="drawerColumns.columnWidth('tags')">
                    <template #cell="{ record }">
                      <ChunkTagList :structured_tags="record.structured_tags" :keywords="record.keywords" />
                    </template>
                  </a-table-column>
                  <a-table-column title="内容预览" data-index="preview" :width="drawerColumns.columnWidth('preview')">
                    <template #cell="{ record }">
                      <div class="preview-cell" :class="{ muted: !record.content_preview }">
                        <div class="preview-text">{{ record.content_preview || '旧记录无预览' }}</div>
                        <details v-if="hasTechnicalFields(record)" class="tech-details">
                          <summary>技术字段</summary>
                          <dl class="tech-grid">
                            <template v-for="field in technicalFields(record)" :key="field.label">
                              <dt>{{ field.label }}</dt>
                              <dd :title="field.value">{{ field.value }}</dd>
                            </template>
                          </dl>
                        </details>
                      </div>
                    </template>
                  </a-table-column>
                  <a-table-column title="定位" data-index="jump" :width="drawerColumns.columnWidth('jump')" align="center">
                    <template #cell="{ record }">
                      <button
                        class="jump-btn"
                        :disabled="!record.document_id"
                        :title="!record.document_id ? '缺少文档信息' : '打开文档并定位到命中切片'"
                        @click="openDocument(record)"
                      >
                        定位
                      </button>
                    </template>
                  </a-table-column>
                </template>
              </a-table>
            </div>
          </section>
        </div>
        <div v-else class="drawer-empty">暂无详情</div>
      </a-spin>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, type ComponentPublicInstance } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useRouter } from 'vue-router'
import {
  getQueryStatsRecordDetail,
  type QueryStatsRecord,
  type QueryStatsRecordDetail,
  type RetrievedChunkItem,
} from '../../api/queryStats'
import { useAutoFitColumns } from '../../composables/useAutoFitColumns'
import { FLAVOR_OPTIONS, flavorLabel, retrievalPathLabel, searchModeLabel } from '../../utils/labelMaps'
import ChunkTagList from '../common/ChunkTagList.vue'

const props = defineProps<{
  records: QueryStatsRecord[]
  total: number
  currentPage: number
  flavorFilter: string
  filterUserId?: string
}>()

const emit = defineEmits<{
  'page-change': [page: number]
  'flavor-change': [flavor: string]
}>()

const router = useRouter()
const drawerOpen = ref(false)
const drawerLoading = ref(false)
const drawerRecord = ref<QueryStatsRecord | QueryStatsRecordDetail | null>(null)
const drawerChunks = ref<RetrievedChunkItem[]>([])
const drawerError = ref('')
let detailRequestId = 0
const recordColumns = useAutoFitColumns('enterprise-rag:query-stats-records:auto-v1', {
  created_at: { width: 172, minWidth: 138, maxWidth: 190 },
  query: { width: 280, minWidth: 180, flex: true },
  status: { width: 74, minWidth: 64, maxWidth: 92 },
  retrieval_flavor: { width: 86, minWidth: 70, maxWidth: 100 },
  strict_evidence: { width: 88, minWidth: 74, maxWidth: 100 },
  result_count: { width: 68, minWidth: 58, maxWidth: 78 },
  rerank_avg_score: { width: 108, minWidth: 84, maxWidth: 120 },
  total_ms: { width: 68, minWidth: 58, maxWidth: 86 },
  details: { width: 80, minWidth: 62, maxWidth: 92 },
}, { minWidth: 52 })
const drawerColumns = useAutoFitColumns('enterprise-rag:query-stats-drawer:auto-v2', {
  rank: { width: 50, minWidth: 44, maxWidth: 60 },
  hit: { width: 232, minWidth: 160, maxWidth: 300 },
  path: { width: 90, minWidth: 72, maxWidth: 130 },
  score: { width: 82, minWidth: 70, maxWidth: 96 },
  tags: { width: 126, minWidth: 96, maxWidth: 170 },
  preview: { width: 430, minWidth: 260, flex: true },
  jump: { width: 68, minWidth: 60, maxWidth: 86 },
}, { minWidth: 44 })

interface DisplayPair {
  key: string
  label: string
  value: string
}

interface TimingPair {
  key: string
  label: string
  ms: number
}

const TIMING_LABELS: Record<string, string> = {
  entity_confirm: '实体确认',
  query_plan: '查询计划',
  rewrite: '查询改写',
  hyde: 'HyDE',
  query_expansion: '查询扩展',
  search: '检索',
  dense_search: '向量检索',
  sparse_search: '关键词检索',
  rrf_fusion: 'RRF 融合',
  table_expand: '表格扩展',
  rerank: '重排',
  post_rerank_fallback: '重排后回退',
  diversify_context: '上下文去重',
  context_expand: '邻近扩展',
  multi_hop: '多跳发现',
  prompt_build: 'Prompt 构建',
  citation_validation: '引用校验',
  groundedness: '依据覆盖',
  retrieval_wall: '检索总耗时',
  first_token: '首 Token',
  generate: '答案生成',
  total: '总耗时',
}

const SETTING_LABELS: Record<string, string> = {
  retrieval_flavor: '检索策略',
  strict_evidence: '仅基于资料',
  entity_mode: '实体模式',
  selected_entities: '命中实体',
  fallback_policy: 'Fallback 策略',
  budget: '检索预算',
  search_limit: '检索上限',
  hyde_limit: 'HyDE 上限',
  rrf_top_k: '融合 Top K',
  rerank_candidate_k: '重排候选',
  final_context_k: '最终上下文',
  max_context_chars: '上下文字符',
  budget_reason: '预算原因',
  use_hybrid: '混合检索',
  use_hyde: 'HyDE',
  use_query_expansion: '查询扩展',
  use_multi_hop: '多跳',
  use_rerank: '重排',
  use_table_expand: '表格扩展',
  use_context_expand: '邻近扩展',
}

const RESULT_SHAPE_LABELS: Record<string, string> = {
  retrieved_chunks_count: '召回切片',
  rerank_candidates_count: '重排候选',
  final_context_chunks_count: '最终上下文',
  citations_count: '引用数',
  retrieved_documents_count: '召回文档',
  cited_documents_count: '引用文档',
  avg_rerank_score: '平均重排分',
  top_rerank_score: '最高重排分',
  context_map_entries: '上下文编号',
  empty_result_reason: '空结果原因',
}

const FALLBACK_LABELS: Record<string, string> = {
  used: '已使用',
  blocked: '已阻止',
  reason: '原因',
  mode: '模式',
  original_entity_filter: '原实体过滤',
  retry_entity_filter: '重试实体过滤',
}

const TOKEN_LABELS: Record<string, string> = {
  available: '可用',
  model: '模型',
  prompt_tokens: '输入 Token',
  completion_tokens: '输出 Token',
  total_tokens: '总 Token',
}

const timingPairs = computed<TimingPair[]>(() => {
  const timings = timingSource(drawerRecord.value)
  return Object.entries(timings)
    .map(([key, value]) => ({ key, label: timingLabel(key), ms: numberValue(value) }))
    .filter((pair): pair is TimingPair => pair.ms !== null && pair.ms >= 0 && pair.key !== 'total')
    .sort((a, b) => b.ms - a.ms)
})

const timingMax = computed(() => Math.max(0, ...timingPairs.value.map((pair) => pair.ms)))
const slowestTimingKey = computed(() => {
  const explicit = stringValue(drawerRecord.value?.slowest_stage?.key)
  if (explicit) return explicit
  return timingPairs.value[0]?.key || ''
})
const slowestStageLabel = computed(() => {
  const key = slowestTimingKey.value
  const ms = numberValue(drawerRecord.value?.slowest_stage?.ms)
  if (!key) return ''
  return ms !== null ? `${timingLabel(key)} ${formatMs(ms)}` : timingLabel(key)
})
const settingPairs = computed(() => kvPairs(settingsSource(drawerRecord.value), SETTING_LABELS))
const resultShapePairs = computed(() => kvPairs(resultShapeSource(drawerRecord.value), RESULT_SHAPE_LABELS))
const fallbackPairs = computed(() => kvPairs(fallbackSource(drawerRecord.value), FALLBACK_LABELS))
const tokenPairs = computed(() => kvPairs(tokenSource(drawerRecord.value), TOKEN_LABELS))
const citationRows = computed(() => citationsForRecord(drawerRecord.value))

function setRecordsTableContainer(element: Element | ComponentPublicInstance | null) {
  recordColumns.containerRef.value = element instanceof HTMLElement ? element : null
}

function setDrawerTableContainer(element: Element | ComponentPublicInstance | null) {
  drawerColumns.containerRef.value = element instanceof HTMLElement ? element : null
}

function onPageChange(page: number) {
  emit('page-change', page)
}

function onFlavorChange(value: unknown) {
  emit('flavor-change', typeof value === 'string' ? value : '')
}

function parseChunks(record: QueryStatsRecord | QueryStatsRecordDetail): { chunks: RetrievedChunkItem[]; error: string } {
  if (!record.retrieved_chunks) return { chunks: [], error: '' }
  try {
    const parsed = JSON.parse(record.retrieved_chunks)
    if (!Array.isArray(parsed)) return { chunks: [], error: '命中记录格式异常' }
    return { chunks: parsed, error: '' }
  } catch {
    return { chunks: [], error: '命中记录解析失败' }
  }
}

function chunksForRecord(record: QueryStatsRecord | QueryStatsRecordDetail): { chunks: RetrievedChunkItem[]; error: string } {
  const detailChunks = (record as QueryStatsRecordDetail).retrieved_chunks_list
  if (Array.isArray(detailChunks)) return { chunks: detailChunks, error: '' }
  return parseChunks(record)
}

async function openDetail(record: QueryStatsRecord) {
  const requestId = ++detailRequestId
  const { chunks, error } = chunksForRecord(record)
  drawerRecord.value = record
  drawerChunks.value = chunks
  drawerError.value = error
  drawerOpen.value = true
  drawerLoading.value = true
  try {
    const detail = await getQueryStatsRecordDetail(record.id, props.filterUserId || '')
    if (requestId !== detailRequestId) return
    const parsed = chunksForRecord(detail)
    drawerRecord.value = detail
    drawerChunks.value = parsed.chunks
    drawerError.value = parsed.error
  } catch (e: any) {
    if (requestId !== detailRequestId) return
    const message = e?.response?.data?.detail || '查询详情加载失败'
    drawerError.value = message
    Message.error(message)
  } finally {
    if (requestId === detailRequestId) drawerLoading.value = false
  }
}

function openDocument(chunk: RetrievedChunkItem) {
  if (!chunk.document_id) return
  router.push({
    path: `/documents/${chunk.document_id}`,
    query: highlightQuery(chunk),
  })
}

function highlightQuery(chunk: RetrievedChunkItem) {
  if (chunk.chunk_key) return { highlight_chunk_key: chunk.chunk_key }
  if (chunk.chunk_id != null) return { highlight_chunk: String(chunk.chunk_id) }
  return undefined
}

function displayFileTitle(record: RetrievedChunkItem): string {
  return record.file_title || '未命名文档'
}

function formatLocation(record: RetrievedChunkItem): string {
  const parts: string[] = []
  if (record.section_title) parts.push(record.section_title)
  if (record.page !== null && record.page !== undefined) parts.push(`第 ${record.page} 页`)
  if (record.table_id) parts.push('表格')
  return parts.join(' / ') || '未标注位置'
}

function formatPath(record: RetrievedChunkItem): string {
  return retrievalPathLabel(record.retrieval_path || record.stage || 'primary')
}

function formatScore(score?: number | null): string {
  return typeof score === 'number' ? score.toFixed(4) : '-'
}

function rawValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  return String(value)
}

function objectRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function objectFromRecord(
  record: QueryStatsRecord | QueryStatsRecordDetail | null,
  observabilityKey: string,
  recordKey: string,
): Record<string, unknown> {
  if (!record) return {}
  const observability = objectRecord((record as QueryStatsRecordDetail).observability)
  const fromObservability = objectRecord(observability[observabilityKey])
  if (Object.keys(fromObservability).length) return fromObservability
  return objectRecord((record as unknown as Record<string, unknown>)[recordKey])
}

function timingSource(record: QueryStatsRecord | QueryStatsRecordDetail | null): Record<string, unknown> {
  return objectFromRecord(record, 'timings_ms', 'timings')
}

function settingsSource(record: QueryStatsRecord | QueryStatsRecordDetail | null): Record<string, unknown> {
  return objectFromRecord(record, 'resolved_settings', 'resolved_settings')
}

function resultShapeSource(record: QueryStatsRecord | QueryStatsRecordDetail | null): Record<string, unknown> {
  return objectFromRecord(record, 'result_shape', 'result_shape')
}

function fallbackSource(record: QueryStatsRecord | QueryStatsRecordDetail | null): Record<string, unknown> {
  return objectFromRecord(record, 'fallback_info', 'fallback_details')
}

function tokenSource(record: QueryStatsRecord | QueryStatsRecordDetail | null): Record<string, unknown> {
  return objectFromRecord(record, 'token_usage', 'token_usage')
}

function numberValue(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === 'boolean' || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? Math.round(n) : null
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function timingLabel(key: string): string {
  return TIMING_LABELS[key] || humanizeKey(key)
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function kvPairs(source: Record<string, unknown>, labels: Record<string, string>): DisplayPair[] {
  return Object.entries(source)
    .filter(([, value]) => isDisplayable(value))
    .map(([key, value]) => ({
      key,
      label: labels[key] || humanizeKey(key),
      value: formatDisplayValue(value),
    }))
}

function isDisplayable(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0
  return true
}

function formatDisplayValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4)
  if (Array.isArray(value)) {
    if (!value.length) return '-'
    if (value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))) {
      return value.map((item) => formatDisplayValue(item)).join(', ')
    }
    return JSON.stringify(value)
  }
  if (value && typeof value === 'object') return JSON.stringify(value)
  return rawValue(value) || '-'
}

function timingBarStyle(ms: number): Record<string, string> {
  const max = timingMax.value || ms
  const width = max > 0 ? Math.max(5, Math.round((ms / max) * 100)) : 0
  return { width: `${width}%` }
}

function isSlowestTiming(key: string): boolean {
  return key === slowestTimingKey.value
}

function endpointLabel(endpoint: string): string {
  const map: Record<string, string> = {
    query_chat_stream: '流式问答',
    query_chat: '非流式问答',
  }
  return map[endpoint] || endpoint
}

function citationsForRecord(record: QueryStatsRecord | QueryStatsRecordDetail | null): Record<string, unknown>[] {
  if (!record) return []
  const detailCitations = (record as QueryStatsRecordDetail).citations_list
  if (Array.isArray(detailCitations)) return detailCitations
  if (!record.citations) return []
  try {
    const parsed = JSON.parse(record.citations)
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === 'object') : []
  } catch {
    return []
  }
}

function citationKey(citation: Record<string, unknown>, index: number): string {
  return stringValue(citation.id || citation.chunk_key || citation.document_id || index)
}

function citationId(citation: Record<string, unknown>, index: number): string {
  return stringValue(citation.id) || `C${index + 1}`
}

function citationTitle(citation: Record<string, unknown>): string {
  return stringValue(citation.file_title || citation.document_title || citation.source || citation.document_id) || '未命名引用'
}

function citationMeta(citation: Record<string, unknown>): string {
  const parts = [
    stringValue(citation.section_title),
    citation.page !== null && citation.page !== undefined ? `第 ${citation.page} 页` : '',
    stringValue(citation.entity_name),
    stringValue(citation.table_id) ? '表格' : stringValue(citation.source_type),
  ].filter(Boolean)
  return parts.join(' / ') || '未标注位置'
}

function technicalFields(record: RetrievedChunkItem): Array<{ label: string; value: string }> {
  return [
    { label: 'chunk_id', value: rawValue(record.chunk_id) },
    { label: 'chunk_key', value: rawValue(record.chunk_key) },
    { label: 'document_id', value: rawValue(record.document_id) },
    { label: 'source_type', value: rawValue(record.source_type) },
    { label: 'keywords', value: rawValue(record.keywords?.join(', ')) },
    { label: 'structured_tags', value: rawValue(record.structured_tags?.join(', ')) },
    { label: 'stage', value: rawValue(record.stage) },
    { label: 'table_id', value: rawValue(record.table_id) },
  ].filter((field) => field.value)
}

function hasTechnicalFields(record: RetrievedChunkItem): boolean {
  return technicalFields(record).length > 0
}

function formatTime(value: string) {
  if (!value) return '-'
  const normalized = value.replace('T', ' ')
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!match) return normalized.slice(0, 19)
  return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`
}

function flavorValue(record: QueryStatsRecord): string {
  return record.retrieval_flavor || 'balanced'
}

function formatRerank(value?: number | null): string {
  return typeof value === 'number' ? value.toFixed(3) : '-'
}

function formatMs(ms: number): string {
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms + 'ms'
}

function timingTitle(record: QueryStatsRecord): string {
  return [
    `检索 ${formatMs(record.retrieval_wall_ms || 0)}`,
    `首 Token ${formatMs(record.first_token_ms || 0)}`,
    `生成 ${formatMs(record.generate_ms || 0)}`,
  ].join(' / ')
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    success: '成功',
    search_failed: '检索失败',
    llm_failed: '生成失败',
    query_failed: '查询失败',
    client_aborted: '已中断',
    timeout: '超时',
    failed: '失败',
  }
  return map[status] || status || '-'
}

function statusClass(status: string): string {
  if (status === 'success') return 'status-success'
  if (status === 'client_aborted') return 'status-aborted'
  return 'status-failed'
}
</script>

<style scoped>
.records-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
}

.records-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.records-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

.records-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.records-table :deep(.arco-table-th) {
  white-space: nowrap;
}

.resize-title {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 100%;
  min-width: 0;
}

.resize-title.center {
  justify-content: center;
}

.manual-resize-handle {
  position: absolute;
  top: -8px;
  right: -8px;
  bottom: -8px;
  width: 8px;
  cursor: col-resize;
}

.manual-resize-handle:hover {
  background: rgba(37, 99, 235, 0.08);
}

.time-cell {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.query-cell,
.path-cell,
.hit-title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flavor-tag,
.strict-tag,
.status-tag {
  display: inline-block;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  font-family: var(--font-display);
  white-space: nowrap;
  vertical-align: middle;
}

.flavor-tag {
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}

.flavor-exact {
  color: #7c2d12;
  border-color: #fed7aa;
  background: #fff7ed;
}

.flavor-recall {
  color: #166534;
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.flavor-discovery {
  color: #6d28d9;
  border-color: #ddd6fe;
  background: #f5f3ff;
}

.strict-tag {
  color: var(--text-muted);
  border: 1px solid var(--border);
  background: var(--bg-hover);
}

.strict-tag.on {
  color: #991b1b;
  border-color: #fecaca;
  background: #fef2f2;
}

.time-ms,
.score-cell {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  white-space: nowrap;
}

.time-dash,
.drawer-empty {
  color: var(--text-muted);
}

.quality-cell {
  white-space: nowrap;
}

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-section {
  min-width: 0;
}

.section-title {
  margin-bottom: 8px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}

.run-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.run-summary span {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-hover);
  color: var(--text-secondary);
  font-size: 12px;
}

.timing-list {
  display: grid;
  gap: 7px;
}

.timing-row {
  display: grid;
  grid-template-columns: 104px minmax(120px, 1fr) 64px 38px;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.timing-label,
.timing-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timing-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.timing-track {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-hover);
}

.timing-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent-dim);
}

.timing-row.slowest .timing-label,
.timing-row.slowest .timing-value {
  color: var(--accent);
  font-weight: 700;
}

.timing-row.slowest .timing-bar {
  background: var(--accent);
}

.slowest-badge {
  justify-self: start;
  padding: 1px 5px;
  border-radius: 4px;
  color: #1d4ed8;
  background: #eff6ff;
  font-size: 11px;
  white-space: nowrap;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
}

.kv-grid {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 6px 10px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-hover);
}

.kv-grid dt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}

.kv-grid dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.citation-list {
  display: grid;
  gap: 6px;
}

.citation-row {
  display: grid;
  grid-template-columns: 54px minmax(160px, 0.6fr) minmax(180px, 1fr);
  gap: 10px;
  align-items: center;
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-surface);
  font-size: 12px;
}

.citation-id {
  color: var(--accent);
  font-weight: 700;
}

.citation-title,
.citation-meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-title {
  color: var(--text-primary);
  font-weight: 600;
}

.citation-meta {
  color: var(--text-muted);
}

.drawer-table-wrap {
  min-width: 0;
  overflow-x: hidden;
}

.hit-summary {
  min-width: 0;
}

.hit-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.hit-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 5px;
}

.meta-pill {
  max-width: 132px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-hover);
  color: var(--text-muted);
  font-size: 11px;
  line-height: 18px;
}

.path-cell {
  color: var(--text-secondary);
}

.preview-cell {
  min-width: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.preview-cell.muted {
  color: var(--text-muted);
}

.preview-text {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.tech-details {
  margin-top: 6px;
  color: var(--text-muted);
}

.tech-details summary {
  width: max-content;
  cursor: pointer;
  font-size: 11px;
  user-select: none;
}

.tech-grid {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 4px 8px;
  margin: 6px 0 0;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-hover);
}

.tech-grid dt {
  color: var(--text-muted);
}

.tech-grid dd {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.status-success {
  color: var(--success, #52c41a);
  background: rgba(82, 196, 26, 0.08);
  border: 1px solid rgba(82, 196, 26, 0.3);
}

.status-failed {
  color: var(--danger, #f5222d);
  background: rgba(245, 34, 45, 0.08);
  border: 1px solid rgba(245, 34, 45, 0.3);
}

.status-aborted {
  color: var(--text-muted);
  background: var(--bg-hover);
  border: 1px solid var(--border);
}

.details-btn,
.jump-btn {
  border: 1px solid var(--border-accent);
  background: var(--accent-subtle);
  color: var(--accent);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.details-btn:hover,
.jump-btn:not(:disabled):hover {
  background: var(--accent);
  color: #fff;
}

.jump-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.drawer-error {
  padding: 12px;
  color: var(--error);
  font-size: 13px;
}

.drawer-empty {
  padding: 12px;
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 860px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .timing-row {
    grid-template-columns: 88px minmax(86px, 1fr) 58px 34px;
    gap: 7px;
  }

  .citation-row {
    grid-template-columns: 44px minmax(0, 1fr);
  }

  .citation-meta {
    grid-column: 2;
  }
}
</style>
