<template>
  <div class="records-card">
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
        <a-table-column data-index="hits" :width="recordColumns.columnWidth('hits')" align="center">
          <template #title>
            <span class="resize-title center">
              命中
              <span class="manual-resize-handle" @mousedown="recordColumns.startResize('hits', $event)" />
            </span>
          </template>
          <template #cell="{ record }">
            <button v-if="hasChunks(record)" class="hits-btn" @click="openHits(record)">查看</button>
            <span v-else class="hits-empty">-</span>
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
      title="检索命中详情"
      :footer="false"
      @cancel="drawerOpen = false"
    >
      <div v-if="drawerRecord" class="run-summary">
        <span>策略：{{ flavorLabel(drawerRecord.retrieval_flavor) }}</span>
        <span>仅基于资料回答：{{ drawerRecord.strict_evidence ? '是' : '否' }}</span>
        <span>主检索：{{ searchModeLabel(drawerRecord.search_mode) }}</span>
        <span>假设文档：{{ searchModeLabel(drawerRecord.search_mode_hyde) }}</span>
      </div>
      <div v-if="drawerError" class="drawer-error">{{ drawerError }}</div>
      <div v-else-if="!drawerChunks.length" class="drawer-empty">暂无命中记录</div>
      <a-table
        v-else
        :data="drawerChunks"
        :pagination="{ pageSize: 20, size: 'small' }"
        row-key="rank"
        size="small"
      >
        <template #columns>
          <a-table-column title="#" data-index="rank" :width="50" />
          <a-table-column title="命中信息" :width="232">
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
          <a-table-column title="召回路径" :width="90">
            <template #cell="{ record }">
              <span class="path-cell" :title="formatPath(record)">{{ formatPath(record) }}</span>
            </template>
          </a-table-column>
          <a-table-column title="分数" :width="82">
            <template #cell="{ record }">
              <span class="score-cell">{{ formatScore(record.score) }}</span>
            </template>
          </a-table-column>
          <a-table-column title="内容预览" :width="430">
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
          <a-table-column title="定位" :width="68" align="center">
            <template #cell="{ record }">
              <button
                class="jump-btn"
                :disabled="!record.document_id"
                :title="!record.document_id ? '缺少文档信息' : '打开文档并定位到命中 chunk'"
                @click="openDocument(record)"
              >
                定位
              </button>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { QueryStatsRecord, RetrievedChunkItem } from '../../api/queryStats'
import { useResizableColumns } from '../../composables/useResizableColumns'
import { FLAVOR_OPTIONS, flavorLabel, retrievalPathLabel, searchModeLabel } from '../../utils/labelMaps'

defineProps<{
  records: QueryStatsRecord[]
  total: number
  currentPage: number
  flavorFilter: string
}>()

const emit = defineEmits<{
  'page-change': [page: number]
  'flavor-change': [flavor: string]
}>()

const router = useRouter()
const drawerOpen = ref(false)
const drawerRecord = ref<QueryStatsRecord | null>(null)
const drawerChunks = ref<RetrievedChunkItem[]>([])
const drawerError = ref('')
const recordColumns = useResizableColumns('enterprise-rag:query-stats-records:v1', {
  created_at: 172,
  query: 276,
  status: 74,
  retrieval_flavor: 86,
  strict_evidence: 88,
  result_count: 68,
  rerank_avg_score: 108,
  total_ms: 68,
  hits: 80,
})

function onPageChange(page: number) {
  emit('page-change', page)
}

function onFlavorChange(value: unknown) {
  emit('flavor-change', typeof value === 'string' ? value : '')
}

function hasChunks(record: QueryStatsRecord): boolean {
  return !!record.retrieved_chunks && record.retrieved_chunks !== '[]'
}

function parseChunks(record: QueryStatsRecord): { chunks: RetrievedChunkItem[]; error: string } {
  if (!record.retrieved_chunks) return { chunks: [], error: '' }
  try {
    const parsed = JSON.parse(record.retrieved_chunks)
    if (!Array.isArray(parsed)) return { chunks: [], error: '命中记录格式异常' }
    return { chunks: parsed, error: '' }
  } catch {
    return { chunks: [], error: '命中记录解析失败' }
  }
}

function openHits(record: QueryStatsRecord) {
  const { chunks, error } = parseChunks(record)
  drawerRecord.value = record
  drawerChunks.value = chunks
  drawerError.value = error
  drawerOpen.value = true
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

function technicalFields(record: RetrievedChunkItem): Array<{ label: string; value: string }> {
  return [
    { label: 'chunk_id', value: rawValue(record.chunk_id) },
    { label: 'chunk_key', value: rawValue(record.chunk_key) },
    { label: 'document_id', value: rawValue(record.document_id) },
    { label: 'source_type', value: rawValue(record.source_type) },
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
    client_aborted: '已中断',
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
.hits-empty {
  color: var(--text-muted);
}

.quality-cell {
  white-space: nowrap;
}

.run-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
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

.hits-btn,
.jump-btn {
  border: 1px solid var(--border-accent);
  background: var(--accent-subtle);
  color: var(--accent);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.hits-btn:hover,
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
</style>
