import { ref } from 'vue'
import { defineStore } from 'pinia'
import {
  getQueryStats,
  getQueryStatsTrend,
  getQueryStatsRecords,
  type QueryStats,
  type QueryStatsTrend,
  type QueryStatsRecord,
} from '../api/queryStats'

export const useQueryStatsStore = defineStore('queryStats', () => {
  const loading = ref(false)
  const stats = ref<QueryStats | null>(null)
  const trend = ref<QueryStatsTrend | null>(null)
  const records = ref<QueryStatsRecord[]>([])
  const recordsTotal = ref(0)

  async function fetchAll() {
    loading.value = true
    try {
      const [s, t, r] = await Promise.all([
        getQueryStats(),
        getQueryStatsTrend(),
        getQueryStatsRecords(),
      ])
      stats.value = s
      trend.value = t
      records.value = r.records
      recordsTotal.value = r.total
    } finally {
      loading.value = false
    }
  }

  async function fetchRecords(page: number, filterUserId: string = '') {
    const r = await getQueryStatsRecords(page, 20, filterUserId)
    records.value = r.records
    recordsTotal.value = r.total
  }

  return { loading, stats, trend, records, recordsTotal, fetchAll, fetchRecords }
})
