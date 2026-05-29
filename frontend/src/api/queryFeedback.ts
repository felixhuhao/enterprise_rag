import apiClient from './client'

export interface FeedbackRecord {
  id: number
  session_id: string
  message_id: string
  query: string
  answer: string
  citations: string
  retrieved_chunks: string
  rating: string
  comment: string
  user_id: string
  created_at: string
}

export interface FeedbackPayload {
  session_id: string
  message_id: string
  query: string
  answer: string
  citations: object[]
  retrieved_chunks: object[]
  rating: string
  comment: string
}

export async function submitFeedback(payload: FeedbackPayload): Promise<{ ok: boolean }> {
  const res = await apiClient.post('/query/feedback', payload)
  return res.data
}

export async function listFeedback(filterUserId: string = ''): Promise<FeedbackRecord[]> {
  const params: Record<string, string> = {}
  if (filterUserId) params.filter_user_id = filterUserId
  const res = await apiClient.get('/query/feedback', { params })
  return res.data
}

export async function promoteFeedbackToGoldenDraft(
  feedbackId: number,
): Promise<{ ok: boolean; status: string; path: string; draft: object }> {
  const res = await apiClient.post(`/query/feedback/${feedbackId}/golden-draft`)
  return res.data
}
