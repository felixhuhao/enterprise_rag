<!--
  评估看板 — 检索统计
-->
<template>
  <div class="evaluate-page">
    <div class="evaluate-header">
      <div>
        <h3>查询质量与运行状态</h3>
        <p>跟踪成功率、未完成率、扩大范围比例、相关性重排分数和端到端耗时。</p>
      </div>
      <a-select v-if="authStore.isAdmin" v-model="filterUserId" :style="{ width: '160px' }" size="small"
                placeholder="筛选记录用户" @change="onFilterChange" allow-clear>
        <a-option value="">全部用户</a-option>
        <a-option value="u_alice">Alice</a-option>
        <a-option value="u_bob">Bob</a-option>
        <a-option value="u_admin">Admin</a-option>
      </a-select>
    </div>
    <a-spin :loading="queryStatsStore.loading" style="width: 100%">
      <QueryStatsCards
        :stats="queryStatsStore.stats"
        :by-flavor="queryStatsStore.statsByFlavor"
        :by-strict="queryStatsStore.statsByStrict"
      />
      <QueryStatsRecords
        :records="queryStatsStore.records"
        :total="queryStatsStore.recordsTotal"
        :current-page="currentPage"
        :flavor-filter="flavorFilter"
        @page-change="onPageChange"
        @flavor-change="onFlavorChange"
      />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useQueryStatsStore } from '../../stores/queryStats'
import { useAuthStore } from '../../stores/auth'
import QueryStatsCards from './QueryStatsCards.vue'
import QueryStatsRecords from './QueryStatsRecords.vue'

const queryStatsStore = useQueryStatsStore()
const authStore = useAuthStore()
const currentPage = ref(1)
const filterUserId = ref('')
const flavorFilter = ref('')

onMounted(() => {
  queryStatsStore.fetchAll(filterUserId.value)
})

async function onFilterChange() {
  currentPage.value = 1
  await queryStatsStore.fetchAll(filterUserId.value)
  if (flavorFilter.value) {
    await queryStatsStore.fetchRecords(1, filterUserId.value, flavorFilter.value)
  }
}

async function onPageChange(page: number) {
  currentPage.value = page
  await queryStatsStore.fetchRecords(page, filterUserId.value, flavorFilter.value)
}

async function onFlavorChange(flavor: string) {
  flavorFilter.value = flavor
  currentPage.value = 1
  await queryStatsStore.fetchRecords(1, filterUserId.value, flavorFilter.value)
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
