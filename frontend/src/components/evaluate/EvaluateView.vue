<!--
  评估看板主页面

  组合：统计卡片 + 图表（分布 + 趋势） + 记录表格
-->
<template>
  <div class="evaluate-page">
    <a-spin :loading="store.loading" style="width: 100%">
      <!-- 统计卡片 -->
      <StatsCards :stats="store.stats" />

      <!-- 图表 -->
      <ScoreChart
        :distribution="store.distribution"
        :trend="store.trend"
      />

      <!-- 记录表格 -->
      <RecordsTable
        :records="store.records"
        :total="store.recordsTotal"
        :current-page="currentPage"
        @page-change="onPageChange"
      />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useEvaluateStore } from '../../stores/evaluate'
import StatsCards from './StatsCards.vue'
import ScoreChart from './ScoreChart.vue'
import RecordsTable from './RecordsTable.vue'

const store = useEvaluateStore()
const currentPage = ref(1)

onMounted(() => {
  store.fetchAll()
})

async function onPageChange(page: number) {
  currentPage.value = page
  await store.fetchRecords(page)
}
</script>

<style scoped>
.evaluate-page {
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px;
  height: 100%;
  overflow-y: auto;
}
</style>
