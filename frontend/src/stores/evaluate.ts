/**
 * 评估看板状态管理 (Pinia Store)
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getStats,
  getDistribution,
  getTrend,
  getRecords,
  type EvaluateStats,
  type ScoreBin,
  type EvaluateRecord,
} from '../api/evaluate'

export const useEvaluateStore = defineStore('evaluate', () => {
  const stats = ref<EvaluateStats | null>(null)
  const distribution = ref<ScoreBin[]>([])
  const trend = ref<{ dates: string[]; avg_scores: number[]; counts: number[] } | null>(null)
  const records = ref<EvaluateRecord[]>([])
  const recordsTotal = ref(0)
  const loading = ref(false)

  async function fetchStats() {
    stats.value = await getStats()
  }

  async function fetchDistribution() {
    const data = await getDistribution()
    distribution.value = data.bins
  }

  async function fetchTrend() {
    trend.value = await getTrend()
  }

  async function fetchRecords(page = 1) {
    const data = await getRecords(page)
    records.value = data.records
    recordsTotal.value = data.total
  }

  async function fetchAll() {
    loading.value = true
    try {
      await Promise.all([fetchStats(), fetchDistribution(), fetchTrend(), fetchRecords()])
    } finally {
      loading.value = false
    }
  }

  return {
    stats,
    distribution,
    trend,
    records,
    recordsTotal,
    loading,
    fetchStats,
    fetchDistribution,
    fetchTrend,
    fetchRecords,
    fetchAll,
  }
})
