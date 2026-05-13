/**
 * 评估看板 API
 */
import apiClient from './client'

export interface EvaluateStats {
  total_count: number
  avg_score: number
  high_count: number
  mid_count: number
  low_count: number
  web_search_count: number
}

export interface ScoreBin {
  range: string
  count: number
}

export interface EvaluateRecord {
  id: number
  session_id: string
  input_text: string
  score: number
  from_web_search: boolean
  created_at: string
}

export async function getStats(): Promise<EvaluateStats> {
  const res = await apiClient.get('/evaluate/stats')
  return res.data
}

export async function getDistribution(): Promise<{ bins: ScoreBin[] }> {
  const res = await apiClient.get('/evaluate/distribution')
  return res.data
}

export async function getTrend(): Promise<{
  dates: string[]
  avg_scores: number[]
  counts: number[]
}> {
  const res = await apiClient.get('/evaluate/trend')
  return res.data
}

export async function getRecords(
  page = 1,
  pageSize = 20,
): Promise<{
  records: EvaluateRecord[]
  total: number
  page: number
  page_size: number
}> {
  const res = await apiClient.get('/evaluate/records', {
    params: { page, page_size: pageSize },
  })
  return res.data
}
