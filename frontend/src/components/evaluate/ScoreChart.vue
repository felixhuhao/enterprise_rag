<!--
  评估图表：分数分布柱状图 + 趋势折线图
-->
<template>
  <div class="charts-row">
    <!-- 分数分布柱状图 -->
    <a-card title="分数分布" class="chart-card">
      <v-chart :option="barOption" autoresize style="height: 260px" />
    </a-card>
    <!-- 趋势折线图 -->
    <a-card title="每日平均分趋势" class="chart-card">
      <v-chart :option="lineOption" autoresize style="height: 260px" />
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ScoreBin } from '../../api/evaluate'

use([BarChart, LineChart, TitleComponent, TooltipComponent, GridComponent, CanvasRenderer])

const props = defineProps<{
  distribution: ScoreBin[]
  trend: { dates: string[]; avg_scores: number[] } | null
}>()

const barOption = computed(() => ({
  tooltip: { trigger: 'axis' as const },
  xAxis: {
    type: 'category' as const,
    data: props.distribution.map((b) => b.range),
  },
  yAxis: { type: 'value' as const },
  series: [
    {
      type: 'bar' as const,
      data: props.distribution.map((b) => b.count),
      itemStyle: { color: '#165DFF' },
    },
  ],
}))

const lineOption = computed(() => ({
  tooltip: { trigger: 'axis' as const },
  xAxis: {
    type: 'category' as const,
    data: props.trend?.dates || [],
  },
  yAxis: { type: 'value' as const, min: 0, max: 1 },
  series: [
    {
      type: 'line' as const,
      data: props.trend?.avg_scores || [],
      smooth: true,
      itemStyle: { color: '#00b42a' },
    },
  ],
}))
</script>

<style scoped>
.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}
.chart-card {
  min-height: 320px;
}
</style>
