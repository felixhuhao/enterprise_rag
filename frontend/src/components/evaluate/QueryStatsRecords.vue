<!--
  检索统计记录表格（分页）
-->
<template>
  <div class="records-card">
    <div class="records-title">检索记录</div>
    <a-table
      :data="records"
      :pagination="{
        current: currentPage,
        total: total,
        pageSize: 20,
        showTotal: true,
      }"
      row-key="id"
      @page-change="onPageChange"
    >
      <template #columns>
        <a-table-column title="时间" :width="180">
          <template #cell="{ record }">
            <span class="time-cell">{{ formatTime(record.created_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column title="查询" data-index="query" :ellipsis="true" />
        <a-table-column title="搜索模式" :width="180">
          <template #cell="{ record }">
            <span
              class="mode-tag"
              :class="modeClass(record.search_mode)"
              :title="record.search_mode || '—'"
            >
              {{ record.search_mode || '—' }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="用户" data-index="user_id" :width="90" />
        <a-table-column title="结果" data-index="result_count" :width="70" />
        <a-table-column title="Rerank均值" :width="110">
          <template #cell="{ record }">
            {{ record.rerank_avg_score.toFixed(3) }}
          </template>
        </a-table-column>
        <a-table-column title="Rerank最高" :width="110">
          <template #cell="{ record }">
            {{ record.rerank_top_score.toFixed(3) }}
          </template>
        </a-table-column>
        <a-table-column title="耗时" :width="90">
          <template #cell="{ record }">
            <span v-if="record.total_ms" class="time-ms">{{ formatMs(record.total_ms) }}</span>
            <span v-else class="time-dash">—</span>
          </template>
        </a-table-column>
        <a-table-column title="状态" :width="100">
          <template #cell="{ record }">
            <span
              class="status-tag"
              :class="statusClass(record.status)"
              :title="record.error_code || undefined"
            >
              {{ statusLabel(record.status) }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="命中" :width="80" align="center">
          <template #cell="{ record }">
            <button
              v-if="hasChunks(record)"
              class="hits-btn"
              @click="openHits(record)"
            >
              查看
            </button>
            <span v-else class="hits-empty">—</span>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <a-empty description="暂无检索统计，进行查询后将自动收集" />
      </template>
    </a-table>

    <!-- 命中详情 Drawer -->
    <a-drawer
      :visible="drawerOpen"
      :width="860"
      title="检索命中详情"
      @cancel="drawerOpen = false"
      :footer="false"
    >
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
          <a-table-column title="Score" :width="80">
            <template #cell="{ record }">
              {{ record.score?.toFixed(4) ?? '—' }}
            </template>
          </a-table-column>
          <a-table-column title="Chunk" data-index="chunk_id" :width="80" />
          <a-table-column title="Doc" data-index="document_id" :width="120"
                          :ellipsis="true" />
          <a-table-column title="来源" data-index="stage" :width="70" />
          <a-table-column title="文档" data-index="file_title" :ellipsis="true" />
          <a-table-column title="实体" data-index="entity_name" :width="100" />
          <a-table-column title="章节" data-index="section_title" :width="140" :ellipsis="true" />
          <a-table-column title="类型" data-index="source_type" :width="90" />
          <a-table-column title="路径" :width="120" :ellipsis="true">
            <template #cell="{ record }">
              {{ record.retrieval_path || record.stage || '主检索' }}
            </template>
          </a-table-column>
          <a-table-column title="" :width="60" align="center">
            <template #cell="{ record }">
              <button
                class="jump-btn"
                :disabled="!record.document_id || record.chunk_id == null"
                :title="!record.document_id || record.chunk_id == null ? '缺少定位信息' : '查看文档'"
                @click="jumpToChunk(record)"
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

defineProps<{
  records: QueryStatsRecord[]
  total: number
  currentPage: number
}>()

const emit = defineEmits<{ 'page-change': [page: number] }>()
const router = useRouter()

function onPageChange(page: number) {
  emit('page-change', page)
}

// ── 命中回放 ──

const drawerOpen = ref(false)
const drawerChunks = ref<RetrievedChunkItem[]>([])
const drawerError = ref('')

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
  drawerChunks.value = chunks
  drawerError.value = error
  drawerOpen.value = true
}

function jumpToChunk(chunk: RetrievedChunkItem) {
  if (!chunk.document_id || chunk.chunk_id == null) return
  router.push({
    path: `/documents/${chunk.document_id}`,
    query: { highlight_chunk: String(chunk.chunk_id) },
  })
}

function formatTime(value: string) {
  if (!value) return '—'
  const normalized = value.replace('T', ' ')
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!match) return normalized.slice(0, 19)
  return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`
}

function modeClass(searchMode: string): string {
  if (searchMode.includes('acl_empty')) return 'acl-empty'
  if (searchMode.includes('fallback')) return 'fallback'
  return ''
}

function formatMs(ms: number): string {
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms + 'ms'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    success: '成功',
    search_failed: '检索失败',
    llm_failed: '生成失败',
    client_aborted: '已中断',
  }
  return map[status] || status || '—'
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

.records-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.time-cell {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.mode-tag {
  display: inline-block;
  max-width: 150px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font-display);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}
.mode-tag.acl-empty {
  color: #c2410c;
  border-color: #fdba74;
  background: #fff7ed;
}
.mode-tag.fallback {
  color: var(--warning, #faad14);
  border-color: var(--warning, #faad14);
  background: rgba(250, 173, 20, 0.08);
}

.time-ms {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.time-dash {
  color: var(--text-muted);
}

.status-tag {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--font-display);
  white-space: nowrap;
  vertical-align: middle;
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

.hits-btn {
  border: 1px solid var(--border-accent);
  background: var(--accent-subtle);
  color: var(--accent);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.hits-btn:hover {
  background: var(--accent);
  color: #fff;
}

.hits-empty {
  color: var(--text-muted);
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

.jump-btn {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  cursor: pointer;
}
.jump-btn:not(:disabled):hover {
  color: var(--accent);
  border-color: var(--border-accent);
}
.jump-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
