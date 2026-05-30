import apiClient from './client'

export interface FeedbackRecord {
  id: number
  session_id: string
  message_id: string
  query: string
  answer: string
  citations: string
  retrieved_chunks: string
  retrieval_flavor: string
  strict_evidence: number
  rating: string
  comment: string
  user_id: string
  created_at: string
  in_golden_draft?: boolean
}

export interface GoldenDraft {
  id: string
  question: string
  preferred_flavor: string
  strict_evidence: boolean
  eval_type: string
  expected_answer?: string
  expected_points?: string[]
  expected_documents?: string[]
  min_expected_citations?: number
  source_feedback_id: number
  feedback_rating: string
  feedback_comment: string
  status: string
  created_at: string
  notes?: string
}

export interface GoldenDraftUpdate {
  question: string
  preferred_flavor: string
  strict_evidence: boolean
  eval_type: string
  expected_answer: string
  expected_points: string[]
  expected_documents: string[]
  min_expected_citations: number
  notes: string
}

export interface FeedbackPayload {
  session_id: string
  message_id: string
  query: string
  answer: string
  citations: object[]
  retrieved_chunks: object[]
  retrieval_flavor: string
  strict_evidence: boolean
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
): Promise<{ ok: boolean; status: string; path: string; draft: GoldenDraft }> {
  const res = await apiClient.post(`/query/feedback/${feedbackId}/golden-draft`)
  return res.data
}

export async function listGoldenDrafts(): Promise<{ path: string; drafts: GoldenDraft[] }> {
  const res = await apiClient.get('/query/feedback/golden-drafts')
  return res.data
}

export async function updateGoldenDraft(
  draftId: string,
  payload: GoldenDraftUpdate,
): Promise<{ ok: boolean; path: string; draft: GoldenDraft }> {
  const res = await apiClient.put(`/query/feedback/golden-drafts/${encodeURIComponent(draftId)}`, payload)
  return res.data
}

export async function deleteGoldenDraft(draftId: string): Promise<{ ok: boolean; path: string }> {
  const res = await apiClient.delete(`/query/feedback/golden-drafts/${encodeURIComponent(draftId)}`)
  return res.data
}

export async function publishGoldenDraft(
  draftId: string,
): Promise<{ ok: boolean; path: string; draft_path: string; case: unknown }> {
  const res = await apiClient.post(`/query/feedback/golden-drafts/${encodeURIComponent(draftId)}/publish`)
  return res.data
}
