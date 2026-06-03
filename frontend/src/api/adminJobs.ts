import apiClient from './client'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | string

export interface JobRecord {
  job_id: string
  job_type: string
  status: JobStatus
  status_label: string
  resource_type: string
  resource_id: string
  progress_current: number
  progress_total: number
  progress_percent: number | null
  message: string
  error_code: string
  error_detail: string
  attempt_count: number
  created_by: string
  created_at: string
  started_at: string
  finished_at: string
  updated_at: string
}

export interface JobListResponse {
  count: number
  jobs: JobRecord[]
}

export interface JobDetailResponse {
  job: JobRecord
}

export interface JobListParams {
  status?: string
  job_type?: string
  resource_type?: string
  resource_id?: string
  limit?: number
}

export async function listJobs(params: JobListParams = {}): Promise<JobListResponse> {
  const res = await apiClient.get('/admin/jobs', { params })
  return res.data
}

export async function getJob(jobId: string): Promise<JobRecord> {
  const res = await apiClient.get<JobDetailResponse>(`/admin/jobs/${jobId}`)
  return res.data.job
}
