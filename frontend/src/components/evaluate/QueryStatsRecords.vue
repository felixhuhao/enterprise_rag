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
              :class="{ fallback: isFallback(record.search_mode) }"
              :title="record.search_mode || '—'"
            >
              {{ record.search_mode || '—' }}
            </span>
          </template>
        </a-table-column>
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
      </template>
      <template #empty>
        <a-empty description="暂无检索统计，进行查询后将自动收集" />
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import type { QueryStatsRecord } from '../../api/queryStats'

defineProps<{
  records: QueryStatsRecord[]
  total: number
  currentPage: number
}>()

const emit = defineEmits<{ 'page-change': [page: number] }>()

function onPageChange(page: number) {
  emit('page-change', page)
}

function formatTime(value: string) {
  if (!value) return '—'
  const normalized = value.replace('T', ' ')
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/)
  if (!match) return normalized.slice(0, 19)
  return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`
}

function isFallback(searchMode: string): boolean {
  return searchMode.includes('fallback')
}

function formatMs(ms: number): string {
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms + 'ms'
}
</script>

<style scoped>
.records-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
}

.records-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
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
</style>
