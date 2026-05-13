<!--
  统计卡片行
-->
<template>
  <div class="stats-cards">
    <a-card class="stat-card" v-for="item in cards" :key="item.label">
      <a-statistic :title="item.label" :value="item.value" :suffix="item.suffix" />
    </a-card>
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
    { label: '总评估次数', value: s.total_count, suffix: '' },
    { label: '平均分数', value: s.avg_score.toFixed(2), suffix: '' },
    { label: '自动批准 (≥0.8)', value: s.high_count, suffix: '' },
    { label: '人工审核 (0.6~0.8)', value: s.mid_count, suffix: '' },
    { label: '自动拒绝 (<0.6)', value: s.low_count, suffix: '' },
    { label: '网络搜索', value: s.web_search_count, suffix: '' },
  ]
})
</script>

<style scoped>
.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.stat-card {
  text-align: center;
}
</style>
