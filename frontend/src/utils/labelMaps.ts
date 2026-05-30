export const FLAVOR_LABELS: Record<string, string> = {
  balanced: '标准问答',
  exact: '精确查找',
  recall: '全面查找',
  discovery: '关联查找',
}

export const FLAVOR_DESCRIPTIONS: Record<string, string> = {
  balanced: '平衡速度和准确率，适合日常资料问答',
  exact: '优先匹配条款、金额、日期和明确事实',
  recall: '扩大召回范围，适合模糊或同义表达',
  discovery: '先发现相关实体，再按实体查找证据',
}

export const FLAVOR_KEYS = ['balanced', 'exact', 'recall', 'discovery'] as const

export const FLAVOR_OPTIONS = FLAVOR_KEYS.map((id) => ({
  id,
  name: FLAVOR_LABELS[id],
  desc: FLAVOR_DESCRIPTIONS[id],
}))

export function flavorLabel(flavor: string): string {
  return FLAVOR_LABELS[flavor || 'balanced'] ?? flavor
}

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  text: '文本',
  table_summary: '表格摘要',
  table_full: '完整表格',
  table_row_group: '表格行组',
}

export function sourceTypeLabel(sourceType: string): string {
  return SOURCE_TYPE_LABELS[sourceType] ?? (sourceType || '未知')
}

export const SEARCH_MODE_LABELS: Record<string, string> = {
  hybrid: '语义 + 关键词',
  dense: '语义匹配',
  sparse: '关键词匹配',
  bm25: '关键词匹配',
  hybrid_filtered: '语义 + 关键词（已过滤）',
  dense_filtered: '语义匹配（已过滤）',
  hybrid_filtered_fallback_unfiltered: '语义 + 关键词（已扩大范围）',
  dense_filtered_fallback_unfiltered: '语义匹配（已扩大范围）',
  hyde: '语义扩展',
  hyde_filtered: '语义扩展（已过滤）',
  hyde_filtered_fallback_unfiltered: '语义扩展（已扩大范围）',
  hyde_failed: '语义扩展（失败）',
  disabled: '已关闭',
  disabled_multi: '已关闭（多实体）',
  acl_empty: '无权限',
  multi_hybrid_filtered: '多实体语义 + 关键词',
  multi_dense_filtered: '多实体语义匹配',
  multi_hop: '多跳发现',
  multi_hop_hop1_only: '多跳发现（仅首轮）',
}

export function searchModeLabel(mode: string | null | undefined): string {
  if (!mode) return '—'
  if (SEARCH_MODE_LABELS[mode]) return SEARCH_MODE_LABELS[mode]

  if (mode.includes('_post_rerank_fallback')) {
    const baseMode = mode.replace('_post_rerank_fallback', '')
    const baseLabel = SEARCH_MODE_LABELS[baseMode] ?? baseMode
    return `${baseLabel}（重排后扩大范围）`
  }

  const expandedFailed = mode.match(/^expanded_(\d+)_failed$/)
  if (expandedFailed) return `扩展查询 ${Number(expandedFailed[1]) + 1}（失败）`

  if (mode.startsWith('multi_')) {
    const inner = mode
      .slice('multi_'.length)
      .split('+')
      .map((part) => SEARCH_MODE_LABELS[part] ?? part)
      .join(' + ')
    return inner ? `多实体：${inner}` : '多实体并行检索'
  }

  return mode
}

const RETRIEVAL_PATH_LABELS: Record<string, string> = {
  primary: '主检索',
  hybrid: '语义 + 关键词',
  hybrid_fallback: '语义 + 关键词（已扩大范围）',
  dense: '语义匹配',
  dense_fallback: '语义匹配（已扩大范围）',
  hyde: '语义扩展',
  hyde_fallback: '语义扩展（已扩大范围）',
  table_expand: '表格扩展',
  context_expand: '补充上下文',
  disabled: '已关闭',
}

export function retrievalPathLabel(path: string | null | undefined): string {
  if (!path) return '主检索'
  const parts = path
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
  const expandedParts = parts.filter((part) => /^expanded_\d+(_fallback)?$/i.test(part))
  return parts
    .map((part) => {
      const normalized = part.toLowerCase()
      const expanded = normalized.match(/^expanded_(\d+)(_fallback)?$/)
      if (expanded) {
        if (expandedParts.length > 1) {
          return part === expandedParts[0]
            ? `扩展查询*${expandedParts.length}${expanded[2] ? '（已扩大范围）' : ''}`
            : ''
        }
        const label = '扩展查询'
        return expanded[2] ? `${label}（已扩大范围）` : label
      }
      return RETRIEVAL_PATH_LABELS[normalized] ?? part
    })
    .filter(Boolean)
    .join(' + ')
}

export const FALLBACK_LABELS = {
  used: '已扩大查找范围',
  blocked: '未扩大查找范围',
}

export const STRATEGY_LABELS = {
  hybridOn: '语义 + 关键词',
  hybridOff: '仅语义',
  hydeOn: '语义扩展',
  hydeOff: '语义扩展已关闭',
  rerankOn: '相关性重排',
  rerankOff: '未重排',
  expansion: '扩展查询',
  strictEvidence: '仅基于资料回答',
  contextExpand: '补充上下文',
  groundedness: '资料支持度',
}

export const STRICT_MODE_LABELS: Record<string, string> = {
  non_strict: '普通回答',
  strict: '仅基于资料回答',
}
