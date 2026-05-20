<!--
  评估图表：分数分布柱状图 + 趋势折线图
-->
<template>
  <div class="charts-row">
    <!-- 分数分布柱状图 -->
    <div class="chart-card">
      <div class="chart-title">分数分布</div>
      <v-chart :option="barOption" autoresize style="height: 240px" />
    </div>
    <!-- 趋势折线图 -->
    <div class="chart-card">
      <div class="chart-title">每日平均分趋势</div>
      <v-chart :option="lineOption" autoresize style="height: 240px" />
    </div>
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
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#1A1F2B',
    borderColor: 'rgba(255,255,255,0.06)',
    textStyle: { color: '#E8ECF4', fontSize: 12 },
  },
  grid: { left: 40, right: 16, top: 12, bottom: 28 },
  xAxis: {
    type: 'category' as const,
    data: props.distribution.map((b) => b.range),
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
    axisLabel: { color: '#505868', fontSize: 11 },
  },
  yAxis: {
    type: 'value' as const,
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
    axisLabel: { color: '#505868', fontSize: 11 },
  },
  series: [
    {
      type: 'bar' as const,
      data: props.distribution.map((b) => b.count),
      itemStyle: {
        color: {
          type: 'linear' as const,
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: '#D4943A' },
            { offset: 1, color: 'rgba(212,148,58,0.2)' },
          ],
        },
        borderRadius: [4, 4, 0, 0],
      },
      barWidth: '50%',
    },
  ],
}))

const lineOption = computed(() => ({
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#1A1F2B',
    borderColor: 'rgba(255,255,255,0.06)',
    textStyle: { color: '#E8ECF4', fontSize: 12 },
  },
  grid: { left: 40, right: 16, top: 12, bottom: 28 },
  xAxis: {
    type: 'category' as const,
    data: props.trend?.dates || [],
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
    axisLabel: { color: '#505868', fontSize: 11 },
  },
  yAxis: {
    type: 'value' as const,
    min: 0,
    max: 1,
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
    axisLabel: { color: '#505868', fontSize: 11 },
  },
  series: [
    {
      type: 'line' as const,
      data: props.trend?.avg_scores || [],
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { color: '#3DD68C', width: 2 },
      itemStyle: { color: '#3DD68C', borderColor: '#12161E', borderWidth: 2 },
      areaStyle: {
        color: {
          type: 'linear' as const,
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(61,214,140,0.15)' },
            { offset: 1, color: 'rgba(61,214,140,0)' },
          ],
        },
      },
    },
  ],
}))
</script>

<style scoped>
.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
}

.chart-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
}

.chart-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
</style>
