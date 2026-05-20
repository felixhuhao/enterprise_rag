<!--
  评估记录表格（分页）
-->
<template>
  <div class="records-card">
    <div class="records-title">最近评估记录</div>
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
        <a-table-column title="时间" data-index="created_at" :width="180" />
        <a-table-column title="用户输入" data-index="input_text" :ellipsis="true" />
        <a-table-column title="分数" :width="100">
          <template #cell="{ record }">
            <span :class="['score-badge', scoreLevel(record.score)]">
              {{ record.score.toFixed(2) }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="网络搜索" :width="100">
          <template #cell="{ record }">
            <span v-if="record.from_web_search" class="search-badge">是</span>
            <span v-else class="text-muted">否</span>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <a-empty description="暂无评估数据，进行聊天对话后将自动收集" />
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import type { EvaluateRecord } from '../../api/evaluate'

const props = defineProps<{
  records: EvaluateRecord[]
  total: number
  currentPage: number
}>()

const emit = defineEmits<{ 'page-change': [page: number] }>()

function onPageChange(page: number) {
  emit('page-change', page)
}

function scoreLevel(score: number): string {
  if (score >= 0.8) return 'high'
  if (score >= 0.6) return 'mid'
  return 'low'
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

.score-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 12px;
}
.score-badge.high {
  background: rgba(61, 214, 140, 0.1);
  color: var(--success);
}
.score-badge.mid {
  background: rgba(232, 168, 56, 0.1);
  color: var(--warning);
}
.score-badge.low {
  background: rgba(240, 96, 96, 0.1);
  color: var(--danger);
}

.search-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 8px;
  background: rgba(91, 156, 246, 0.1);
  color: var(--info);
  font-size: 12px;
  font-weight: 500;
}

.text-muted {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
