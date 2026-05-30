<!--
  检索链路面板 — 显示在 assistant 消息上方
  收起: entity / search_mode / results_count
  展开: query rewrite + trace + rerank scores
-->
<template>
  <div class="retrieval-info">
    <!-- 收起状态：核心 tag -->
    <span class="tag">{{ info.results_count }} 条结果</span>
    <span v-if="entityTag.text" class="tag" :class="entityTag.cls">{{ entityTag.text }}</span>
    <span v-if="combinedSearchModeLabel" class="tag" :class="{ warn: combinedWarn }">
      {{ combinedSearchModeLabel }}
    </span>
    <span v-if="expansionCount" class="tag accent">{{ STRATEGY_LABELS.expansion }} {{ expansionCount }}</span>
    <span v-if="fallbackTag.text" class="tag" :class="fallbackTag.cls">
      {{ fallbackTag.text }}
    </span>
    <span v-if="info.rewritten_query" class="tag">改写: {{ info.rewritten_query }}</span>

    <span class="tag clickable" @click="expanded = !expanded">
      {{ expanded ? '收起' : '检索链路' }}
    </span>

    <!-- 展开状态：trace + rerank -->
    <template v-if="expanded">
      <!-- Multi-hop trace -->
      <div v-if="info.hop_plan === 'discovery' && info.hop_trace?.length" class="hop-trace-panel">
        <div class="hop-trace-title" @click="showHopTrace = !showHopTrace">
          多跳发现
          <span class="hop-count">{{ info.hop_trace.length }} hops</span>
        </div>
        <template v-if="showHopTrace">
          <div class="hop-row" v-for="(hop, i) in info.hop_trace" :key="i">
            <div class="hop-label">Hop {{ hop.hop }}</div>
            <div class="hop-detail">
              <span v-if="hop.query">查询: {{ hop.query }}</span>
              <span v-if="hop.discovered_entities?.length">
                发现实体: {{ hop.discovered_entities.join('、') }}
              </span>
              <span v-if="hop.per_entity_counts">
                命中: <template v-for="(cnt, ent) in hop.per_entity_counts" :key="ent">{{ ent }}×{{ cnt }} </template>
              </span>
              <span class="hop-status" :class="'hop-' + hop.status">{{ hop.status }}</span>
            </div>
            <div class="hop-count-badge">{{ hop.result_count }} results</div>
          </div>
        </template>
      </div>

      <!-- Trace 链路 -->
      <div v-if="fallbackDetail" class="fallback-panel" :class="{ blocked: info.fallback_info?.blocked }">
        {{ fallbackDetail }}
      </div>

      <div v-if="aliasTraceEntries.length" class="alias-panel">
        <div class="alias-row" v-for="row in aliasTraceEntries" :key="row.alias + row.text">
          <span class="alias-label">{{ row.ambiguous ? '歧义别名' : '匹配别名' }}</span>
          <span class="alias-text">{{ row.text }}</span>
        </div>
      </div>

      <div v-if="queryExpansionEntries.length" class="expansion-panel">
        <div class="expansion-row" v-for="row in queryExpansionEntries" :key="row.label">
          <span class="expansion-label">{{ row.label }}</span>
          <span class="expansion-query">{{ row.query }}</span>
          <span class="expansion-count">{{ row.count }} 条</span>
        </div>
      </div>

      <div v-if="traceRows.length" class="trace-panel">
        <div class="trace-row" v-for="row in traceRows" :key="row.label">
          <span class="trace-label">{{ row.label }}</span>
          <span v-if="row.value" class="trace-value">{{ row.value }}</span>
          <span v-if="row.ms != null" class="trace-ms">{{ row.ms }}ms</span>
        </div>
        <div class="trace-divider"></div>
        <div class="trace-row" v-if="trace?.retrieval_wall_ms != null">
          <span class="trace-label">检索总计 (wall)</span>
          <span class="trace-ms total">{{ trace.retrieval_wall_ms }}ms</span>
        </div>
        <div class="trace-row" v-if="trace?.first_token_ms != null">
          <span class="trace-label">首 Token</span>
          <span class="trace-ms">{{ trace.first_token_ms }}ms</span>
        </div>
        <div class="trace-row" v-if="trace?.generate_ms != null">
          <span class="trace-label">生成</span>
          <span class="trace-ms">{{ trace.generate_ms }}ms</span>
        </div>
        <div class="trace-divider" v-if="trace?.total_ms != null"></div>
        <div class="trace-row" v-if="trace?.total_ms != null">
          <span class="trace-label total">总耗时</span>
          <span class="trace-ms total">{{ trace.total_ms }}ms</span>
        </div>
      </div>

      <!-- Rerank 表格（现有） -->
      <div v-if="rerankItems.length" class="rerank-table-wrap">
        <table class="rerank-table">
          <thead>
            <tr>
              <th>#</th>
              <th>文件</th>
              <th>章节</th>
              <th>类型</th>
              <th>LLM</th>
              <th>RRF</th>
              <th>综合</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in rerankItems" :key="item.index">
              <td>{{ item.index }}</td>
              <td class="cell-ellipsis" :title="item.file_title">{{ item.file_title }}</td>
              <td class="cell-ellipsis" :title="item.section_title">{{ item.section_title || '—' }}</td>
              <td>{{ sourceTypeLabel(item.source_type) }}</td>
              <td>{{ item.llm_score }}</td>
              <td>{{ item.rrf_score }}</td>
              <td class="cell-score">{{ item.final_score }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RetrievalInfo as RetrievalInfoType, RerankItem, TraceData } from '../../stores/queryChat'
import { FALLBACK_LABELS, STRATEGY_LABELS, searchModeLabel, sourceTypeLabel } from '../../utils/labelMaps'

function resolveSearchMode(mode: string, modeHyde: string): { label: string; warn: boolean } {
  const all = [mode, modeHyde].filter(Boolean)
  const labels = all
    .map((item) => searchModeLabel(item))
    .filter((label) => label && label !== '—' && label !== '已关闭')
  return {
    label: Array.from(new Set(labels)).join(' + '),
    warn: all.some((item) => item.includes('fallback')),
  }
}

const props = withDefaults(defineProps<{
  info: RetrievalInfoType
  rerankItems?: RerankItem[]
  trace?: TraceData
}>(), {
  rerankItems: () => [],
})

const expanded = ref(false)
const showHopTrace = ref(false)

const resolved = computed(() => resolveSearchMode(props.info.search_mode, props.info.search_mode_hyde))
const combinedSearchModeLabel = computed(() => resolved.value.label)
const combinedWarn = computed(() => resolved.value.warn)

const fallbackTag = computed(() => {
  const info = props.info.fallback_info
  if (info?.used) return { text: FALLBACK_LABELS.used, cls: 'warn' }
  if (info?.blocked) return { text: FALLBACK_LABELS.blocked, cls: 'blocked' }
  return { text: '', cls: '' }
})

const fallbackDetail = computed(() => {
  const info = props.info.fallback_info
  if (!info?.used && !info?.blocked) return ''
  const scope = filterToScope(info.original_filter)
  if (info.used) {
    return `${scope} -> 全部资料：原范围证据不足，已扩大查找范围。回答不会把全局证据自动归因到原实体。`
  }
  return `${scope}：当前模式禁止扩大到全部资料，证据不足时应直接说明无法确认。`
})

const entityTag = computed(() => {
  const mode = props.info.entity_mode
  if (mode === 'multi_explicit') {
    const entities = props.info.matched_entities ?? []
    return { text: `多实体: ${entities.join('、')}`, cls: 'accent' }
  }
  if (mode === 'broad' || mode === 'none') {
    return { text: '全局搜索', cls: '' }
  }
  // single or fallback
  if (props.info.entity) {
    return { text: `主体: ${props.info.entity}`, cls: 'accent' }
  }
  return { text: '', cls: '' }
})

function filterToScope(filter: string) {
  const matched = filter.match(/entity_name == "([^"]+)"/)
  return matched?.[1] || '原实体范围'
}

interface TraceRow {
  label: string
  value?: string
  ms?: number
}

interface QueryExpansionRow {
  label: string
  query: string
  count: number
}

const expansionCount = computed(() => props.info.expanded_queries?.length ?? 0)

const aliasTraceEntries = computed(() => {
  return (props.info.alias_trace ?? []).map((row) => {
    const target = row.ambiguous
      ? `[${(row.canonicals ?? []).join(' / ')}]（已跳过）`
      : row.canonical
    return {
      alias: row.alias,
      ambiguous: row.ambiguous,
      text: `"${row.alias}" -> ${target || '-'}`,
    }
  })
})

const queryExpansionEntries = computed<QueryExpansionRow[]>(() => {
  const trace = props.info.query_expansion_trace ?? []
  if (trace.length) {
    return trace.map(row => ({
      label: expansionLabel(row.label),
      query: row.query,
      count: row.count,
    }))
  }
  const expanded = props.info.expanded_queries ?? []
  const counts = props.info.per_query_counts ?? {}
  return expanded.map((query, index) => ({
    label: `扩展查询 ${index + 1}`,
    query,
    count: counts[`expanded_${index}`] ?? 0,
  }))
})

function expansionLabel(label: string) {
  if (label === 'original') return '原始查询'
  const matched = label.match(/^expanded_(\d+)$/)
  if (matched) return `扩展查询 ${matched[1]}`
  return label
}

const traceRows = computed<TraceRow[]>(() => {
  const t = props.trace
  if (!t) return []
  const rows: TraceRow[] = []
  if (t.entity_confirm_ms != null) rows.push({ label: '主体确认', value: entityTag.value.text || undefined, ms: t.entity_confirm_ms })
  if (t.rewrite_ms != null) rows.push({ label: '查询改写', value: props.info.rewritten_query || undefined, ms: t.rewrite_ms })
  if (t.search_hyde_ms != null) rows.push({ label: expansionCount.value ? `搜索 + ${STRATEGY_LABELS.expansion}` : '搜索 + 假设文档（并行）', ms: t.search_hyde_ms })
  if (t.rrf_fusion_ms != null) rows.push({ label: 'RRF 融合', ms: t.rrf_fusion_ms })
  if (t.table_expand_ms != null) rows.push({ label: '表格扩展', ms: t.table_expand_ms })
  if (t.rerank_ms != null) rows.push({ label: STRATEGY_LABELS.rerankOn, ms: t.rerank_ms })
  if (t.post_rerank_fallback_ms != null) rows.push({ label: '重排后扩大范围', ms: t.post_rerank_fallback_ms })
  if (t.context_expand_ms != null) rows.push({ label: STRATEGY_LABELS.contextExpand, ms: t.context_expand_ms })
  if (t.build_prompt_ms != null) rows.push({ label: 'Prompt 构建', ms: t.build_prompt_ms })
  return rows
})
</script>

<style scoped>
.retrieval-info {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.tag {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font-display);
}
.tag.accent {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--accent-subtle);
}
.tag.warn {
  color: var(--warning);
  border-color: #fed7aa;
  background: #fff7ed;
}
.tag.blocked {
  color: #991b1b;
  border-color: #fecaca;
  background: #fef2f2;
}
.tag.clickable {
  cursor: pointer;
  user-select: none;
}
.tag.clickable:hover {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--accent-subtle);
}

/* Trace panel */
.fallback-panel {
  width: 100%;
  margin-top: 4px;
  padding: 8px 12px;
  border: 1px solid #fed7aa;
  border-radius: var(--radius-md);
  background: #fff7ed;
  color: #92400e;
  font-size: 12px;
  line-height: 1.6;
}

.fallback-panel.blocked {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}

.expansion-panel {
  width: 100%;
  margin-top: 4px;
  padding: 8px 12px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: var(--radius-md);
}

.alias-panel {
  width: 100%;
  margin-top: 4px;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.alias-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
  font-size: 12px;
}

.alias-label {
  min-width: 64px;
  color: var(--accent);
  font-weight: 600;
}

.alias-text {
  color: var(--text-secondary);
}

.expansion-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
  font-size: 12px;
}

.expansion-label {
  min-width: 72px;
  color: #1d4ed8;
  font-weight: 600;
}

.expansion-query {
  flex: 1;
  color: var(--text-secondary);
}

.expansion-count {
  color: var(--text-muted);
  white-space: nowrap;
}

.trace-panel {
  width: 100%;
  margin-top: 4px;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.trace-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
  font-family: var(--font-display);
  font-size: 12px;
}

.trace-label {
  color: var(--text-secondary);
  min-width: 140px;
  flex-shrink: 0;
}
.trace-label.total {
  font-weight: 600;
  color: var(--text-primary);
}

.trace-value {
  color: var(--text-muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-ms {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  margin-left: auto;
  flex-shrink: 0;
}
.trace-ms.total {
  font-weight: 600;
  color: var(--accent);
}

.trace-divider {
  height: 1px;
  background: var(--border);
  margin: 6px 0;
}

/* Rerank table */
.rerank-table-wrap {
  width: 100%;
  overflow-x: auto;
  margin-top: 4px;
}

.rerank-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: var(--font-display);
}

.rerank-table th,
.rerank-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}

.rerank-table th {
  color: var(--text-muted);
  font-weight: 500;
}

.rerank-table td {
  color: var(--text-secondary);
}

.cell-ellipsis {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-score {
  font-weight: 600;
  color: var(--text-primary);
}

/* Multi-hop trace */
.hop-trace-panel {
  width: 100%;
  margin-top: 4px;
  padding: 8px 12px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: var(--radius-md);
}

.hop-trace-title {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: #166534;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.hop-count { font-weight: 400; color: var(--text-muted); }

.hop-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid #dcfce7;
  font-size: 11px;
}
.hop-row:last-child { border-bottom: none; }

.hop-label {
  font-weight: 600;
  color: #166534;
  min-width: 40px;
}

.hop-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: var(--text-secondary);
}

.hop-status {
  font-size: 10px;
  font-weight: 500;
  padding: 0 4px;
  border-radius: 999px;
}
.hop-ok { color: #166534; }
.hop-no_entities_found { color: #92400e; }
.hop-hop2_failed { color: #991b1b; }
.hop-no_results { color: var(--text-muted); }

.hop-count-badge {
  color: var(--text-muted);
  white-space: nowrap;
}
</style>
