export function evalModeLabel(value: string): string {
  if (value === 'quick') return '快速(旧)'
  if (value === 'retrieval_only') return '仅检索'
  if (value === 'answer_lite') return '轻答案'
  return '完整'
}

export function evalTypeLabel(value: string): string {
  if (value === 'rule') return '规则'
  if (value === 'llm_judge') return 'LLM'
  if (value === 'no_answer') return '拒答'
  return value || '-'
}

export function failureCategoryLabel(value: string): string {
  if (value === 'retrieval_miss') return '检索未命中'
  if (value === 'rerank_drop') return '重排丢失'
  if (value === 'context_loss') return '命中未引用'
  if (value === 'citation_miss') return '引用未命中'
  if (value === 'answer_incomplete') return '答案不完整'
  if (value === 'answer_unsupported') return '答案无依据'
  if (value === 'no_answer_wrong') return '拒答错误'
  if (value === 'judge_uncertain') return 'Judge不确定'
  if (value === 'pending_judge') return '等待Judge'
  if (value === 'timeout') return '超时'
  if (value === 'unknown') return '未知'
  return value || '-'
}

export function judgeCacheLabel(value: string): string {
  if (value === 'cached') return 'Judge缓存命中'
  if (value === 'fresh') return 'Judge新评分'
  if (value === 'miss') return 'Judge缓存未命中'
  if (value === 'error') return 'Judge错误'
  return value || '-'
}

export function evalResultStatusLabel(value: string): string {
  if (value === 'passed') return '通过'
  if (value === 'warning') return '警告'
  if (value === 'failed') return '失败'
  if (value === 'running') return '运行中'
  if (value === 'queued') return '等待'
  return value || '-'
}

export function formatEvalScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return value.toFixed(2)
}

export function formatEvalMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `${Math.round(value)}ms`
}
