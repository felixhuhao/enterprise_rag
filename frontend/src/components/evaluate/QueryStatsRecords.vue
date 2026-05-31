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
        <span>语义扩展：{{ searchModeLabel(drawerRecord.search_mode_hyde) }}</span>
      </div>
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
                <div v-if="chunkTags(record).length" class="chunk-tags" :title="chunkTagsTitle(record)">
                  <span v-for="tag in chunkTags(record)" :key="tag.value" class="chunk-tag">
                    {{ tag.label }}
                  </span>
                  <span v-if="hiddenChunkTagCount(record)" class="chunk-tag more">
                    +{{ hiddenChunkTagCount(record) }}
                  </span>
                </div>
                <span v-else class="muted-text">—</span>
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
                  :title="!record.document_id ? '缺少文档信息' : '打开文档并定位到命中 chunk'"
                  @click="openDocument(record)"
                >
                  定位
                </button>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, type ComponentPublicInstance } from 'vue'
import { useRouter } from 'vue-router'
import type { QueryStatsRecord, RetrievedChunkItem } from '../../api/queryStats'
import { useAutoFitColumns } from '../../composables/useAutoFitColumns'
import { FLAVOR_OPTIONS, flavorLabel, retrievalPathLabel, searchModeLabel, structuredTagLabel } from '../../utils/labelMaps'

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
const recordColumns = useAutoFitColumns('enterprise-rag:query-stats-records:auto-v1', {
  created_at: { width: 172, minWidth: 138, maxWidth: 190 },
  query: { width: 280, minWidth: 180, flex: true },
  status: { width: 74, minWidth: 64, maxWidth: 92 },
  retrieval_flavor: { width: 86, minWidth: 70, maxWidth: 100 },
  strict_evidence: { width: 88, minWidth: 74, maxWidth: 100 },
  result_count: { width: 68, minWidth: 58, maxWidth: 78 },
  rerank_avg_score: { width: 108, minWidth: 84, maxWidth: 120 },
  total_ms: { width: 68, minWidth: 58, maxWidth: 86 },
  hits: { width: 80, minWidth: 62, maxWidth: 92 },
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

function chunkTags(record: RetrievedChunkItem) {
  return uniqueStrings(record.structured_tags).slice(0, 3).map((value) => ({
    value,
    label: structuredTagLabel(value),
  }))
}

function hiddenChunkTagCount(record: RetrievedChunkItem) {
  return Math.max(0, uniqueStrings(record.structured_tags).length - chunkTags(record).length)
}

function chunkTagsTitle(record: RetrievedChunkItem) {
  const structured = uniqueStrings(record.structured_tags).map(structuredTagLabel)
  const keywords = uniqueStrings(record.keywords)
  const parts = []
  if (structured.length) parts.push(`标签：${structured.join(' / ')}`)
  if (keywords.length) parts.push(`关键词：${keywords.join(' / ')}`)
  return parts.join('\n')
}

function uniqueStrings(values: string[] | null | undefined) {
  return Array.from(new Set((values ?? []).filter(Boolean)))
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

.chunk-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: flex-start;
}

.chunk-tag {
  max-width: 100%;
  padding: 2px 6px;
  border-radius: 999px;
  color: #166534;
  background: #dcfce7;
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chunk-tag.more {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.muted-text {
  color: var(--text-muted);
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
