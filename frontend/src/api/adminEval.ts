import apiClient from './client'

export interface EvalSummary {
  overall: {
    count: number
    avg_score: number
    pass_rate: number
  }
  per_breakdown?: Record<string, unknown>
  low_score_cases?: Array<{ id: string; final_score: number; question: string }>
}

export interface EvalStatus {
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  started_at: string
  finished_at: string
  summary: EvalSummary | null
  result_path: string
  summary_path: string
  error: string
}

export async function getEvalStatus(): Promise<EvalStatus> {
  const res = await apiClient.get('/admin/eval/status')
  return res.data
}

export async function runEval(judge: boolean = false): Promise<{ ok: boolean; status: string }> {
  const res = await apiClient.post('/admin/eval/run', { judge })
  return res.data
}
