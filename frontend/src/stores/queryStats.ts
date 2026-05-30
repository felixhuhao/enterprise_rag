import { ref } from 'vue'
import { defineStore } from 'pinia'
import {
  getQueryStats,
  getQueryStatsTrend,
  getQueryStatsByFlavor,
  getQueryStatsByStrict,
  getQueryStatsRecords,
  type QueryStats,
  type QueryStatsTrend,
  type QueryStatsByFlavor,
  type QueryStatsByStrict,
  type QueryStatsRecord,
} from '../api/queryStats'

export const useQueryStatsStore = defineStore('queryStats', () => {
  const loading = ref(false)
  const stats = ref<QueryStats | null>(null)
  const trend = ref<QueryStatsTrend | null>(null)
  const statsByFlavor = ref<QueryStatsByFlavor | null>(null)
  const statsByStrict = ref<QueryStatsByStrict | null>(null)
  const records = ref<QueryStatsRecord[]>([])
  const recordsTotal = ref(0)

  async function fetchAll(filterUserId: string = '') {
    loading.value = true
    try {
      const [s, t, bf, bs, r] = await Promise.all([
        getQueryStats(filterUserId),
        getQueryStatsTrend(filterUserId),
        getQueryStatsByFlavor(filterUserId),
        getQueryStatsByStrict(filterUserId),
        getQueryStatsRecords(1, 20, filterUserId),
      ])
      stats.value = s
      trend.value = t
      statsByFlavor.value = bf
      statsByStrict.value = bs
      records.value = r.records
      recordsTotal.value = r.total
    } finally {
      loading.value = false
    }
  }

  async function fetchRecords(page: number, filterUserId: string = '', flavor: string = '') {
    const r = await getQueryStatsRecords(page, 20, filterUserId, flavor)
    records.value = r.records
    recordsTotal.value = r.total
  }

  return {
    loading,
    stats,
    trend,
    statsByFlavor,
    statsByStrict,
    records,
    recordsTotal,
    fetchAll,
    fetchRecords,
  }
})
