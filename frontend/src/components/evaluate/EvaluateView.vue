<!--
  评估看板 — 检索统计
-->
<template>
  <div class="evaluate-page">
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
  padding: 24px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.3s var(--ease-out);
}
</style>
