<!--
  统计卡片行
-->
<template>
  <div class="stats-cards stagger">
    <div class="stat-card" v-for="item in cards" :key="item.label">
      <div class="stat-value">{{ formatValue(item) }}</div>
      <div class="stat-label">{{ item.label }}</div>
      <div class="stat-glow" :style="{ background: item.glow }"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvaluateStats } from '../../api/evaluate'

const props = defineProps<{ stats: EvaluateStats | null }>()

const cards = computed(() => {
  const s = props.stats
  if (!s) return []
  return [
    { label: '总评估次数', value: s.total_count, precision: 0, glow: 'rgba(212, 148, 58, 0.06)' },
    { label: '平均分数', value: s.avg_score, precision: 2, glow: 'rgba(91, 156, 246, 0.06)' },
    { label: '自动批准 ≥0.8', value: s.high_count, precision: 0, glow: 'rgba(61, 214, 140, 0.06)' },
    { label: '人工审核 0.6~0.8', value: s.mid_count, precision: 0, glow: 'rgba(232, 168, 56, 0.06)' },
    { label: '自动拒绝 <0.6', value: s.low_count, precision: 0, glow: 'rgba(240, 96, 96, 0.06)' },
    { label: '网络搜索', value: s.web_search_count, precision: 0, glow: 'rgba(91, 156, 246, 0.06)' },
  ]
})

function formatValue(item: { value: number; precision: number }) {
  return typeof item.value === 'number'
    ? item.precision > 0 ? item.value.toFixed(item.precision) : item.value
    : item.value
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
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
  transition: border-color 0.2s var(--ease-out), transform 0.2s var(--ease-out);
}
.stat-card:hover {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.stat-glow {
  position: absolute;
  top: 0;
  right: 0;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  filter: blur(20px);
  opacity: 0;
  transition: opacity 0.3s var(--ease-out);
  pointer-events: none;
}
.stat-card:hover .stat-glow {
  opacity: 1;
}

.stat-value {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-label {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-top: 6px;
}
</style>
