<!--
  评估看板 — 检索统计
-->
<template>
  <div class="evaluate-page">
    <div class="evaluate-header">
      <div>
        <h3>查询质量与运行状态</h3>
        <p>跟踪成功率、未完成率、fallback、rerank 分数和端到端耗时。</p>
      </div>
    </div>
    <a-spin :loading="queryStatsStore.loading" style="width: 100%">
      <QueryStatsCards :stats="queryStatsStore.stats" />
      <QueryStatsRecords
        :records="queryStatsStore.records"
        :total="queryStatsStore.recordsTotal"
        :current-page="currentPage"
        @page-change="onPageChange"
      />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useQueryStatsStore } from '../../stores/queryStats'
import QueryStatsCards from './QueryStatsCards.vue'
import QueryStatsRecords from './QueryStatsRecords.vue'

const queryStatsStore = useQueryStatsStore()
const currentPage = ref(1)

onMounted(() => {
  queryStatsStore.fetchAll()
})

async function onPageChange(page: number) {
  currentPage.value = page
  await queryStatsStore.fetchRecords(page)
}
</script>

<style scoped>
.evaluate-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}
.evaluate-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.evaluate-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}
.evaluate-header p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
</style>
