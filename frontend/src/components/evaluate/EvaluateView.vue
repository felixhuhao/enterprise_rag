<!--
  评估看板 — 检索统计
-->
<template>
  <div class="evaluate-page">
    <a-tabs :active-key="activeTab" class="quality-tabs" animation @change="onTabChange">
      <template v-if="authStore.isAdmin" #extra>
        <a-select v-model="filterUserId" :style="{ width: '160px' }" size="small"
                  placeholder="筛选记录用户" @change="onFilterChange" allow-clear>
          <a-option value="">全部用户</a-option>
          <a-option value="u_alice">Alice</a-option>
          <a-option value="u_bob">Bob</a-option>
          <a-option value="u_admin">Admin</a-option>
        </a-select>
      </template>
      <a-tab-pane key="overview" title="概览">
        <a-spin :loading="queryStatsStore.loading" style="width: 100%">
          <QueryStatsCards
            :stats="queryStatsStore.stats"
            :by-flavor="queryStatsStore.statsByFlavor"
            :by-strict="queryStatsStore.statsByStrict"
          />
        </a-spin>
      </a-tab-pane>
      <a-tab-pane key="records" title="检索记录">
        <a-spin :loading="queryStatsStore.loading" style="width: 100%">
          <QueryStatsRecords
            :records="queryStatsStore.records"
            :total="queryStatsStore.recordsTotal"
            :current-page="currentPage"
            :flavor-filter="flavorFilter"
            :filter-user-id="filterUserId"
            @page-change="onPageChange"
            @flavor-change="onFlavorChange"
          />
        </a-spin>
      </a-tab-pane>
      <a-tab-pane v-if="authStore.isAdmin" key="feedback" title="答案反馈">
        <FeedbackRecords :filter-user-id="filterUserId" />
      </a-tab-pane>
      <a-tab-pane v-if="authStore.isAdmin" key="eval" title="回归评测">
        <EvalRunPanel />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQueryStatsStore } from '../../stores/queryStats'
import { useAuthStore } from '../../stores/auth'
import QueryStatsCards from './QueryStatsCards.vue'
import QueryStatsRecords from './QueryStatsRecords.vue'
import EvalRunPanel from './EvalRunPanel.vue'
import FeedbackRecords from '../feedback/FeedbackRecords.vue'

const queryStatsStore = useQueryStatsStore()
const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const currentPage = ref(1)
const filterUserId = ref('')
const flavorFilter = ref('')
const activeTab = ref('overview')
const tabs = ['overview', 'records', 'feedback', 'eval']
const adminTabs = ['feedback', 'eval']

onMounted(() => {
  queryStatsStore.fetchAll(filterUserId.value)
})

watch(
  [() => route.query.tab, () => authStore.isAdmin],
  () => {
    activeTab.value = normalizeTab(route.query.tab)
  },
  { immediate: true },
)

function normalizeTab(value: unknown): string {
  const tab = typeof value === 'string' ? value : 'overview'
  if (!tabs.includes(tab)) return 'overview'
  if (adminTabs.includes(tab) && !authStore.isAdmin) return 'overview'
  return tab
}

function onTabChange(key: string | number) {
  const next = normalizeTab(String(key))
  activeTab.value = next
  router.replace({
    path: '/evaluate',
    query: {
      ...route.query,
      tab: next === 'overview' ? undefined : next,
    },
  })
}

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
  padding: 16px 20px 20px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}
.quality-tabs :deep(.arco-tabs-content) {
  padding-top: 4px;
}

.quality-tabs :deep(.arco-tabs-nav-tab),
.quality-tabs :deep(.arco-tabs-nav-tab-list) {
  padding-left: 0;
}

.quality-tabs :deep(.arco-tabs-nav-type-line .arco-tabs-tab:first-of-type) {
  margin-left: 0 !important;
}
</style>
