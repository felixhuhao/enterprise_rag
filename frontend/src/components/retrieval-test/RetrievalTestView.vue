<template>
  <div class="retrieval-test-page">
    <section class="test-panel">
      <div class="query-toolbar">
        <div class="query-field">
          <a-textarea
            v-model="query"
            placeholder="输入要测试的查询，例如：差旅报销需要哪些审批材料？"
            :auto-size="{ minRows: 2, maxRows: 4 }"
            allow-clear
          />
        </div>
        <div class="run-controls">
          <label class="control-item">
            <span>Top K</span>
            <a-input-number v-model="topK" :min="1" :max="30" size="small" />
          </label>
          <a-button type="primary" :loading="loading" @click="runTest">
            <template #icon><icon-search /></template>
            开始测试
          </a-button>
        </div>
      </div>

      <div class="mode-strip">
        <button
          v-for="mode in flavorModes"
          :key="mode.id"
          class="mode-card"
          :class="{ active: retrievalFlavor === mode.id }"
          type="button"
          @click="retrievalFlavor = mode.id"
        >
          <span class="mode-name">{{ mode.name }}</span>
          <span class="mode-desc">{{ mode.desc }}</span>
        </button>
      </div>
    </section>

    <section v-if="errorMessage" class="error-panel">
      {{ errorMessage }}
    </section>

    <template v-if="response">
      <section class="strategy-panel">
        <div class="strategy-main">
          <div>
            <span class="section-eyebrow">检索链路</span>
            <h3>{{ flavorLabel(response.retrieval_flavor) }}</h3>
            <p>{{ strategyText }}</p>
          </div>
          <div class="strategy-tags">
            <a-tag :color="response.strategy.hybrid ? 'arcoblue' : 'gray'">
              {{ response.strategy.hybrid ? STRATEGY_LABELS.hybridOn : STRATEGY_LABELS.hybridOff }}
            </a-tag>
            <a-tag :color="response.strategy.hyde ? 'purple' : 'gray'">
              {{ response.strategy.hyde ? STRATEGY_LABELS.hydeOn : STRATEGY_LABELS.hydeOff }}
            </a-tag>
            <a-tag v-if="response.strategy.query_expansion" color="arcoblue">
              {{ STRATEGY_LABELS.expansion }} {{ queryExpansionCount }}
            </a-tag>
            <a-tag :color="response.strategy.rerank ? 'green' : 'gray'">
              {{ response.strategy.rerank ? STRATEGY_LABELS.rerankOn : STRATEGY_LABELS.rerankOff }}
            </a-tag>
            <a-tag v-if="response.strategy.fallback" color="orange">
              {{ FALLBACK_LABELS.used }}
            </a-tag>
            <a-tag v-if="response.fallback_info?.blocked" color="red">
              {{ FALLBACK_LABELS.blocked }}
            </a-tag>
          </div>
        </div>

        <div class="strategy-grid">
          <div class="metric">
            <span>结果数</span>
            <strong>{{ response.result_count }}</strong>
            <small v-if="queryBudget?.final_context_k">
              上下文上限 {{ queryBudget.final_context_k }}
            </small>
          </div>
          <div class="metric">
            <span>检索耗时</span>
            <strong>{{ response.trace.retrieval_wall_ms ?? 0 }}ms</strong>
          </div>
          <div class="metric entity-metric">
            <span>匹配实体</span>
            <strong>{{ entityModeLabel }}</strong>
            <small v-if="matchedEntityText">{{ matchedEntityText }}</small>
          </div>
          <div class="metric">
            <span>Embedding</span>
            <strong>{{ response.strategy.embedding_model }}</strong>
          </div>
          <div class="metric">
            <span>LLM</span>
            <strong>{{ response.strategy.chat_model }}</strong>
          </div>
        </div>

        <div v-if="traceEntries.length" class="trace-panel">
          <div class="trace-head">
            <span>执行耗时</span>
            <strong>{{ response.trace.retrieval_wall_ms ?? 0 }}ms</strong>
          </div>
          <div class="trace-grid">
            <div v-for="row in traceEntries" :key="row.key" class="trace-item">
              <span>{{ row.label }}</span>
              <strong>{{ row.value }}ms</strong>
            </div>
          </div>
        </div>

        <div v-if="hopTrace.length || queryExpansionEntries.length" class="chain-grid">
          <div v-if="queryExpansionEntries.length" class="expansion-panel">
            <div class="expansion-head">
              <span>{{ STRATEGY_LABELS.expansion }}</span>
              <strong>{{ queryExpansionCount }} 条</strong>
            </div>
            <div class="expansion-list">
              <div v-for="row in queryExpansionEntries" :key="row.label" class="expansion-item">
                <span class="expansion-label">{{ row.label }}</span>
                <span class="expansion-query">{{ row.query }}</span>
                <span class="expansion-count">{{ row.count }} 条命中</span>
              </div>
            </div>
          </div>

          <div v-if="hopTrace.length" class="hop-panel">
            <div class="hop-head">
              <span>关联路径</span>
              <strong>{{ hopTrace.length }} hops</strong>
            </div>
            <div class="hop-list">
              <div v-for="hop in hopTrace" :key="hop.hop" class="hop-item">
                <span class="hop-step">Hop {{ hop.hop }}</span>
                <div class="hop-detail">
                  <span v-if="hop.query">查询：{{ hop.query }}</span>
                  <span v-if="hop.discovered_entities?.length">
                    发现实体：{{ hop.discovered_entities.join(' / ') }}
                  </span>
                  <span v-if="formatHopCounts(hop)">
                    命中：{{ formatHopCounts(hop) }}
                  </span>
                </div>
                <span class="hop-status">{{ hopStatusLabel(hop.status) }}</span>
                <span class="hop-count">{{ hop.result_count }} 条</span>
              </div>
            </div>
          </div>
        </div>

        <details v-if="budgetEntries.length" :key="budgetDetailsKey" class="debug-details">
          <summary>
            <span>检索预算</span>
            <strong>{{ flavorLabel(response.retrieval_flavor) }}</strong>
          </summary>
          <div class="budget-grid">
            <div v-for="item in budgetEntries" :key="item.key" class="budget-item">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </details>

        <div v-if="fallbackText" class="fallback-note">
          {{ fallbackText }}
        </div>

        <div v-if="aliasTraceEntries.length" class="alias-panel">
          <div class="alias-head">别名匹配</div>
          <div class="alias-list">
            <div v-for="row in aliasTraceEntries" :key="row.alias + row.text" class="alias-item">
              <span class="alias-kind" :class="{ ambiguous: row.ambiguous }">
                {{ row.ambiguous ? '歧义' : '命中' }}
              </span>
              <span class="alias-text">{{ row.text }}</span>
            </div>
          </div>
        </div>

        <!-- Per-entity hit distribution -->
        <div v-if="entityEntries.length" class="entity-dist">
          <span class="entity-dist-label">实体命中分布</span>
          <div v-for="[name, count] in entityEntries" :key="name" class="entity-dist-item">
            <span class="entity-dist-name">{{ name }}</span>
            <span class="entity-dist-count">{{ count }} 条</span>
          </div>
        </div>
      </section>

      <section class="results-panel">
        <div class="results-header">
          <div>
            <h3>Top 切片</h3>
            <p v-if="response.rewritten_query !== response.query">
              改写查询：{{ response.rewritten_query }}
            </p>
            <p v-else>展示最终进入检索上下文的候选切片。</p>
          </div>
          <a-button size="mini" @click="resultColumns.resetColumnWidths()">重置列宽</a-button>
        </div>

        <div :ref="setResultTableContainer" class="retrieval-table-wrap">
          <a-table
            :data="response.results"
            :pagination="{ pageSize: 10 }"
            :bordered="false"
            row-key="rank"
            class="retrieval-table"
            column-resizable
            @column-resize="resultColumns.onColumnResize"
          >
            <template #columns>
              <a-table-column title="#" data-index="rank" :width="resultColumns.columnWidth('rank')" align="center">
                <template #cell="{ record }">
                  <strong>{{ record.rank }}</strong>
                </template>
              </a-table-column>

            <a-table-column title="来源" data-index="source" :width="resultColumns.columnWidth('source')">
              <template #cell="{ record }">
                <div class="source-cell">
                  <button type="button" @click="openDocument(record)">
                    {{ record.file_title || record.document_id }}
                  </button>
                  <span>{{ record.section_title || '—' }}</span>
                </div>
              </template>
            </a-table-column>

            <a-table-column title="页码" data-index="page" :width="resultColumns.columnWidth('page')" align="center">
              <template #cell="{ record }">
                {{ record.page ?? '—' }}
              </template>
            </a-table-column>

            <a-table-column title="路径" data-index="path" :width="resultColumns.columnWidth('path')">
              <template #cell="{ record }">
                <div class="path-cell">
                  <span
                    v-for="path in retrievalPathSummary(record.retrieval_path)"
                    :key="path"
                    class="path-pill"
                    :title="retrievalPathLabel(record.retrieval_path)"
                  >
                    {{ path }}
                  </span>
                  <span
                    v-if="record.context_expanded_chunk_ids?.length"
                    class="path-pill expanded"
                  >
                    补充 {{ record.context_expanded_chunk_ids.join(', ') }}
                  </span>
                </div>
              </template>
            </a-table-column>

            <a-table-column title="分数" data-index="score" :width="resultColumns.columnWidth('score')" align="center">
              <template #cell="{ record }">
                <div class="score-cell">
                  <strong>{{ formatScore(record.final_score ?? record.score) }}</strong>
                  <span v-if="record.llm_score !== null && record.llm_score !== undefined">
                    LLM {{ formatScore(record.llm_score) }}
                  </span>
                </div>
              </template>
            </a-table-column>

            <a-table-column title="类型" data-index="type" :width="resultColumns.columnWidth('type')" align="center">
              <template #cell="{ record }">
                <a-tag :color="sourceTypeColor(record.source_type)" size="small">
                  {{ sourceTypeLabel(record.source_type) }}
                </a-tag>
              </template>
            </a-table-column>

            <a-table-column title="标签" data-index="tags" :width="resultColumns.columnWidth('tags')">
              <template #cell="{ record }">
                <ChunkTagList :structured_tags="record.structured_tags" :keywords="record.keywords" />
              </template>
            </a-table-column>

            <a-table-column title="内容" data-index="content" :width="resultColumns.columnWidth('content')">
              <template #cell="{ record }">
                <div class="content-cell">
                  <p>{{ expandedKeys.has(record.rank) ? record.content : record.content_preview }}</p>
                  <button
                    v-if="record.content.length > record.content_preview.length"
                    type="button"
                    @click="toggleExpand(record.rank)"
                  >
                    {{ expandedKeys.has(record.rank) ? '收起' : '展开' }}
                  </button>
                </div>
              </template>
            </a-table-column>
            </template>
          </a-table>
        </div>
      </section>
    </template>

    <a-empty v-else-if="!loading" class="empty-state" description="输入查询后运行检索测试" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, type ComponentPublicInstance } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { IconSearch } from '@arco-design/web-vue/es/icon'
import { useAutoFitColumns } from '../../composables/useAutoFitColumns'
import ChunkTagList from '../common/ChunkTagList.vue'
import {
  FALLBACK_LABELS,
  FLAVOR_OPTIONS,
  STRATEGY_LABELS,
  flavorLabel,
  retrievalPathLabel,
  searchModeLabel,
  sourceTypeLabel,
} from '../../utils/labelMaps'

defineOptions({ name: 'RetrievalTestView' })
import type { HopTraceEntry, RetrievalBudget, RetrievalTestResponse } from '../../api/retrievalTest'
import { runRetrievalTest } from '../../api/retrievalTest'

const router = useRouter()

const query = ref('差旅报销需要哪些审批材料？')
const topK = ref(10)
const retrievalFlavor = ref('balanced')
const loading = ref(false)
const errorMessage = ref('')
const response = ref<RetrievalTestResponse | null>(null)
const expandedKeys = ref<Set<number>>(new Set())
const resultColumns = useAutoFitColumns('enterprise-rag:retrieval-test-results:auto-v2', {
  rank: { width: 52, minWidth: 44, maxWidth: 64 },
  source: { width: 180, minWidth: 130, maxWidth: 240 },
  page: { width: 64, minWidth: 56, maxWidth: 76 },
  path: { width: 110, minWidth: 84, maxWidth: 150 },
  score: { width: 84, minWidth: 74, maxWidth: 100 },
  type: { width: 96, minWidth: 78, maxWidth: 120 },
  tags: { width: 150, minWidth: 110, maxWidth: 220 },
  content: { width: 520, minWidth: 260, flex: true },
}, { minWidth: 44 })

function setResultTableContainer(element: Element | ComponentPublicInstance | null) {
  resultColumns.containerRef.value = element instanceof HTMLElement ? element : null
}

interface QueryExpansionRow {
  label: string
  query: string
  count: number
}

interface TraceRow {
  key: string
  label: string
  value: number
}

const flavorModes = FLAVOR_OPTIONS

const budgetFields: Array<{ key: keyof RetrievalBudget; label: string }> = [
  { key: 'search_limit', label: '主检索' },
  { key: 'hyde_limit', label: '语义扩展' },
  { key: 'rrf_top_k', label: '融合' },
  { key: 'rerank_candidate_k', label: '重排候选' },
  { key: 'final_context_k', label: '最终上下文' },
  { key: 'max_context_chars', label: '上下文字符' },
  { key: 'per_entity_min_k', label: '单实体保底' },
]

const strategyText = computed(() => {
  if (!response.value) return ''
  const s = response.value.strategy
  const weights = s.hybrid ? `语义 ${s.dense_weight} / 关键词 ${s.sparse_weight}` : '语义 1.0'
  const mode = flavorLabel(response.value.retrieval_flavor || s.retrieval_flavor)
  return `${mode}，Top ${s.top_k}，${weights}，主检索：${searchModeLabel(s.search_mode)}，语义扩展：${s.hyde ? '开启' : '关闭'}`
})

const queryBudget = computed<RetrievalBudget | null>(() => response.value?.query_plan?.budget ?? null)
const budgetDetailsKey = computed(() => {
  const current = response.value
  if (!current) return 'budget'
  return `${current.query}-${current.retrieval_flavor}-${current.result_count}`
})

const budgetEntries = computed(() => {
  const budget = queryBudget.value
  if (!budget) return []
  return budgetFields
    .filter((item) => budget[item.key] !== undefined && budget[item.key] !== null)
    .map((item) => ({
      key: item.key,
      label: item.label,
      value: formatBudgetValue(budget[item.key]),
    }))
})

const hopTrace = computed(() => response.value?.hop_trace ?? [])

const queryExpansionCount = computed(() => response.value?.expanded_queries?.length ?? 0)

const queryExpansionEntries = computed<QueryExpansionRow[]>(() => {
  const current = response.value
  if (!current) return []
  const trace = current.query_expansion_trace ?? []
  if (trace.length) {
    return trace.map(row => ({
      label: expansionLabel(row.label),
      query: row.query,
      count: row.count,
    }))
  }
  const counts = current.per_query_counts ?? {}
  return (current.expanded_queries ?? []).map((query, index) => ({
    label: `扩展查询 ${index + 1}`,
    query,
    count: counts[`expanded_${index}`] ?? 0,
  }))
})

const traceEntries = computed<TraceRow[]>(() => {
  const trace = response.value?.trace ?? {}
  const fields = [
    ['entity_confirm_ms', '实体识别'],
    ['query_plan_ms', '策略规划'],
    ['rewrite_ms', '问题改写'],
    ['search_hyde_ms', '检索'],
    ['multi_hop_ms', '关联发现'],
    ['rrf_fusion_ms', 'RRF 融合'],
    ['table_expand_ms', '表格扩展'],
    ['rerank_ms', '相关性重排'],
    ['context_expand_ms', STRATEGY_LABELS.contextExpand],
  ] as const
  return fields
    .filter(([key]) => trace[key] !== undefined && trace[key] !== null)
    .map(([key, label]) => ({
      key,
      label,
      value: Number(trace[key] ?? 0),
    }))
})

const entityModeLabel = computed(() => {
  if (!response.value) return '—'
  const map: Record<string, string> = {
    single: '单实体',
    multi_explicit: '多实体',
    broad: '宽泛查询',
    multi_hop: '关联查找',
    none: '全库',
  }
  return map[response.value.entity_mode] ?? response.value.entity_mode
})

const matchedEntityText = computed(() => {
  if (!response.value) return ''
  const entities = response.value.matched_entities ?? []
  if (!entities.length) return ''
  return entities.join(' / ')
})

const entityEntries = computed(() => {
  if (!response.value?.per_entity_counts) return []
  return Object.entries(response.value.per_entity_counts)
})

const aliasTraceEntries = computed(() => {
  return (response.value?.alias_trace ?? []).map((row) => {
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

const fallbackText = computed(() => {
  const info = response.value?.fallback_info
  if (!info?.used && !info?.blocked) return ''
  const scope = filterToScope(info.original_filter)
  if (info.used) return `${scope} -> 全部资料：原范围证据不足，已扩大查找范围。`
  return `${scope}：当前模式禁止扩大到全部资料。`
})

async function runTest() {
  const trimmed = query.value.trim()
  if (!trimmed) {
    Message.warning('请输入查询内容')
    return
  }
  loading.value = true
  errorMessage.value = ''
  expandedKeys.value = new Set()
  try {
    response.value = await runRetrievalTest({
      query: trimmed,
      top_k: topK.value,
      use_hybrid: true,
      use_hyde: true,
      use_rerank: true,
      retrieval_flavor: retrievalFlavor.value,
      strict_evidence: false,
    })
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    errorMessage.value = detail || err?.message || '检索测试失败'
  } finally {
    loading.value = false
  }
}

function toggleExpand(rank: number) {
  const next = new Set(expandedKeys.value)
  if (next.has(rank)) {
    next.delete(rank)
  } else {
    next.add(rank)
  }
  expandedKeys.value = next
}

function openDocument(record: RetrievalTestResponse['results'][number]) {
  if (!record.document_id) return
  router.push({
    path: `/documents/${record.document_id}`,
    query: highlightQuery(record),
  })
}

function highlightQuery(record: RetrievalTestResponse['results'][number]) {
  if (record.chunk_key) return { highlight_chunk_key: record.chunk_key }
  if (record.chunk_id != null) return { highlight_chunk: String(record.chunk_id) }
  return undefined
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return Number(value).toFixed(3)
}

function formatBudgetValue(value: RetrievalBudget[keyof RetrievalBudget]) {
  if (typeof value === 'number') return value.toLocaleString('zh-CN')
  return value || '—'
}

function formatHopCounts(hop: HopTraceEntry) {
  const counts = hop.per_entity_counts
  if (!counts || !Object.keys(counts).length) return ''
  return Object.entries(counts).map(([name, count]) => `${name} ${count}`).join(' / ')
}

function hopStatusLabel(status: string) {
  const map: Record<string, string> = {
    ok: '完成',
    no_entities_found: '未发现实体',
    no_results: '无结果',
    hop2_failed: '二跳失败',
  }
  return map[status] ?? status
}

function expansionLabel(label: string) {
  if (label === 'original') return '原始查询'
  const matched = label.match(/^expanded_(\d+)$/)
  if (matched) return `扩展查询 ${matched[1]}`
  return label
}

function sourceTypeColor(sourceType: string) {
  return sourceType.startsWith('table_') ? 'orange' : 'arcoblue'
}

function retrievalPathSummary(path: string | null | undefined) {
  const parts = (path || 'primary')
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
  if (!parts.length) return ['主检索']

  const expandedCount = parts.filter((part) => /^expanded_\d+/i.test(part)).length
  const labels: string[] = []
  if (expandedCount) labels.push(`扩展查询 x${expandedCount}`)
  if (parts.some((part) => part.toLowerCase() === 'hybrid' || part.toLowerCase() === 'primary')) labels.push('主检索')
  if (parts.some((part) => part.toLowerCase() === 'hyde')) labels.push('语义扩展')
  if (parts.some((part) => part.toLowerCase().includes('fallback'))) labels.push('已扩大范围')
  return labels.length ? labels : parts.slice(0, 2).map((part) => retrievalPathLabel(part))
}

function filterToScope(filter: string) {
  const matched = filter.match(/entity_name == "([^"]+)"/)
  return matched?.[1] || '原实体范围'
}
</script>

<style scoped>
.retrieval-test-page {
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.test-panel,
.strategy-panel,
.results-panel,
.error-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
}

.query-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 12px;
  align-items: stretch;
}

.query-field {
  display: flex;
  min-width: 0;
}

.query-field :deep(.arco-textarea-wrapper) {
  height: 100%;
}

.run-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
}

.control-item {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  white-space: nowrap;
}

.control-item :deep(.arco-input-number) {
  width: 92px;
}

.mode-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(130px, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.mode-card {
  min-height: 58px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.mode-card:hover {
  border-color: var(--border-hover);
  background: #f8fafc;
}

.mode-card.active {
  border-color: var(--accent);
  background: var(--accent-subtle);
}

.mode-name {
  display: block;
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
  white-space: nowrap;
}

.mode-card.active .mode-name {
  color: var(--accent);
}

.mode-desc {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 15px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.error-panel {
  margin-top: 14px;
  color: var(--error);
  background: #fff5f5;
  border-color: rgba(220, 38, 38, 0.2);
}

.strategy-panel {
  margin-top: 14px;
}

.strategy-main,
.results-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.results-header > div {
  min-width: 0;
}

.strategy-main h3,
.results-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 17px;
}

.strategy-main p,
.results-header p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.strategy-tags {
  display: inline-flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.section-eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
}

.strategy-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.metric {
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  min-width: 0;
}

.metric span {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
}

.metric strong {
  display: block;
  margin-top: 6px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric small {
  display: block;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entity-metric small {
  max-width: 100%;
}

.trace-panel,
.hop-panel,
.expansion-panel {
  margin-top: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #f8fafc;
  padding: 12px;
}

.trace-head,
.hop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-muted);
  font-size: 12px;
}

.trace-head strong,
.hop-head strong {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}

.trace-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.trace-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 112px;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  font-size: 12px;
}

.trace-item span {
  color: var(--text-muted);
}

.trace-item strong {
  margin-left: auto;
  color: var(--text-primary);
  font-weight: 600;
}

.chain-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.hop-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.hop-item {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) auto auto;
  align-items: start;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  font-size: 12px;
}

.hop-step {
  color: var(--accent);
  font-weight: 700;
  white-space: nowrap;
}

.hop-detail {
  min-width: 0;
  display: grid;
  gap: 3px;
  color: var(--text-secondary);
}

.hop-detail span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hop-status,
.hop-count {
  color: var(--text-muted);
  white-space: nowrap;
}

.expansion-panel {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}

.expansion-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #1d4ed8;
  font-size: 12px;
}

.expansion-head strong {
  color: #1e3a8a;
  font-size: 12px;
  font-weight: 600;
}

.expansion-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.expansion-item {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr) auto;
  align-items: start;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #dbeafe;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  font-size: 12px;
}

.expansion-label {
  color: #1d4ed8;
  font-weight: 700;
  white-space: nowrap;
}

.expansion-query {
  color: var(--text-secondary);
  min-width: 0;
}

.expansion-count {
  color: var(--text-muted);
  white-space: nowrap;
}

.debug-details {
  margin-top: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fbfdff;
  padding: 12px;
}

.debug-details summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  list-style: none;
  color: var(--text-muted);
  font-size: 12px;
}

.debug-details summary::-webkit-details-marker {
  display: none;
}

.debug-details summary::after {
  content: '展开';
  color: var(--text-muted);
  font-size: 12px;
}

.debug-details[open] summary::after {
  content: '收起';
}

.debug-details summary strong {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  margin-left: auto;
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.budget-item {
  min-width: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--border);
}

.budget-item span,
.budget-item strong {
  display: block;
}

.budget-item span {
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.budget-item strong {
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.results-panel {
  margin-top: 14px;
}

.entity-dist {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  align-items: center;
}

.alias-panel {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #f8fafc;
}

.alias-head {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.alias-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.alias-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.alias-kind {
  color: var(--accent);
  font-weight: 700;
  min-width: 32px;
}

.alias-kind.ambiguous {
  color: #92400e;
}

.alias-text {
  color: var(--text-secondary);
}

.fallback-note {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #92400e;
  font-size: 12px;
}

.entity-dist-label {
  font-size: 12px;
  color: var(--text-muted);
}

.entity-dist-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  font-size: 12px;
}

.entity-dist-name {
  color: var(--accent);
  font-weight: 500;
}

.entity-dist-count {
  color: var(--text-muted);
}

.trace-mini {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--text-muted);
  font-size: 12px;
}

.trace-mini span {
  border: 1px solid var(--border);
  background: var(--bg-hover);
  border-radius: 999px;
  padding: 4px 8px;
}

.retrieval-table-wrap {
  min-width: 0;
  overflow-x: hidden;
}

.retrieval-table {
  margin-top: 14px;
}

.source-cell {
  min-width: 0;
}

.source-cell button {
  display: block;
  max-width: 100%;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--accent);
  cursor: pointer;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  white-space: normal;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.35;
  text-align: left;
}

.source-cell span {
  display: block;
  margin-top: 4px;
  max-width: 100%;
  color: var(--text-muted);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  white-space: normal;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.35;
}

.path-cell {
  display: grid;
  gap: 4px;
  justify-items: start;
}

.path-pill {
  display: inline-block;
  max-width: 100%;
  padding: 2px 5px;
  border-radius: 4px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.path-pill.expanded {
  color: #166534;
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.score-cell strong,
.score-cell span {
  display: block;
}

.score-cell strong {
  color: var(--text-primary);
  font-size: 13px;
}

.score-cell span {
  color: var(--text-muted);
  font-size: 11px;
}

.content-cell {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.content-cell p {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.content-cell button {
  flex: 0 0 auto;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 5px 8px;
}

.content-cell button:hover {
  color: var(--accent);
  border-color: var(--border-accent);
}

.empty-state {
  margin-top: 60px;
}

@media (max-width: 1100px) {
  .mode-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chain-grid {
    grid-template-columns: 1fr;
  }

  .strategy-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .budget-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .hop-item {
    grid-template-columns: 64px minmax(0, 1fr);
  }

  .hop-status,
  .hop-count {
    justify-self: start;
  }
}

@media (max-width: 760px) {
  .query-toolbar {
    grid-template-columns: 1fr;
  }

  .run-controls {
    flex-direction: row;
    align-items: center;
  }

  .mode-strip {
    grid-template-columns: 1fr;
  }

  .strategy-main,
  .results-header {
    flex-direction: column;
  }

  .strategy-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .budget-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
