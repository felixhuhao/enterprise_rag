<!--
  检索统计卡片行
-->
<template>
  <div class="stats-cards stagger">
    <div class="stat-card" v-for="item in cards" :key="item.label">
      <div class="stat-value">{{ formatValue(item) }}</div>
      <div class="stat-label">{{ item.label }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QueryStats } from '../../api/queryStats'

const props = defineProps<{ stats: QueryStats | null }>()

const cards = computed(() => {
  const s = props.stats
  if (!s) return []
  return [
    { label: '总查询数', value: s.total_queries, precision: 0 },
    { label: '未完成率', value: formatPercent(s.failure_rate) },
    { label: '平均 Rerank 分', value: s.avg_rerank_score, precision: 3 },
    { label: '平均结果数', value: s.avg_result_count, precision: 1 },
    { label: 'Fallback 次数', value: s.fallback_count, precision: 0 },
    { label: 'Fallback 比例', value: s.fallback_ratio, precision: 3 },
  ]
})

function formatPercent(rate: number): string {
  return (rate * 100).toFixed(1) + '%'
}

function formatValue(item: { value: number | string; precision?: number }) {
  if (typeof item.value === 'string') return item.value
  const p = item.precision ?? 0
  return p > 0 ? item.value.toFixed(p) : item.value
}
</script>

<style scoped>
.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(155px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}

.stat-card {
  position: relative;
  overflow: hidden;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  transition: border-color 0.15s var(--ease-out), background 0.15s var(--ease-out);
}
.stat-card:hover {
  border-color: var(--border-hover);
  background: #f8fafc;
}

.stat-value {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-label {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  margin-top: 6px;
}
</style>
