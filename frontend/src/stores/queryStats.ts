import { ref } from 'vue'
import { defineStore } from 'pinia'
import { Message } from '@arco-design/web-vue'
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
  const error = ref<string | null>(null)

  async function fetchAll(filterUserId: string = '') {
    loading.value = true
    try {
      const [s, t, bf, bs, r] = await Promise.all([
        getQueryStats(filterUserId),
        getQueryStatsTrend(filterUserId),
        getQueryStatsByFlavor(filterUserId),
        getQueryStatsByStrict(filterUserId),
        getQueryStatsRecords(1, 15, filterUserId),
      ])
      stats.value = s
      trend.value = t
      statsByFlavor.value = bf
      statsByStrict.value = bs
      records.value = r.records
      recordsTotal.value = r.total
      error.value = null
    } catch (e: any) {
      const message = e?.response?.data?.detail || '质量统计加载失败'
      error.value = message
      Message.error(message)
    } finally {
      loading.value = false
    }
  }

  async function fetchRecords(page: number, filterUserId: string = '', flavor: string = '') {
    try {
      const r = await getQueryStatsRecords(page, 15, filterUserId, flavor)
      records.value = r.records
      recordsTotal.value = r.total
      error.value = null
    } catch (e: any) {
      const message = e?.response?.data?.detail || '检索记录加载失败'
      error.value = message
      Message.error(message)
    }
  }

  return {
    loading,
    stats,
    trend,
    statsByFlavor,
    statsByStrict,
    records,
    recordsTotal,
    error,
    fetchAll,
    fetchRecords,
  }
})
