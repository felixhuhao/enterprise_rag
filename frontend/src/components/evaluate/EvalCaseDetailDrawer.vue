<template>
  <a-drawer
    :visible="visible"
    width="min(1180px, 94vw)"
    title="评测用例详情"
    :footer="false"
    @cancel="emit('close')"
  >
    <a-spin :loading="loading" class="case-detail-spin">
      <div v-if="error" class="detail-error">{{ error }}</div>
      <div v-else-if="!row" class="detail-empty">暂无详情</div>
      <div v-else class="case-detail">
        <header class="detail-header">
          <div>
            <span class="detail-id">{{ row.id || detail?.case_id }}</span>
            <h3>{{ row.question || '-' }}</h3>
          </div>
          <div class="detail-status">
            <span class="status-pill" :class="'status-' + previewStatus">
              {{ previewLabel }}
            </span>
            <strong>{{ formatEvalScore(row.final_score) || '-' }}</strong>
          </div>
        </header>

        <div class="detail-metrics">
          <span>模式 {{ evalModeLabel(row.eval_mode || '') }}</span>
          <span>评测 {{ evalTypeLabel(row.eval_type || '') }}</span>
          <span>策略 {{ displayFlavor }}</span>
          <span>仅资料 {{ row.strict_evidence ? '是' : '否' }}</span>
          <span>Hit@5 {{ flagLabel(row.hit_at_5) }}</span>
          <span>Hit@10 {{ flagLabel(row.hit_at_10) }}</span>
          <span>Doc@10 {{ flagLabel(row.doc_hit_at_10) }}</span>
          <span>Chunk@10 {{ flagLabel(row.chunk_hit_at_10) }}</span>
          <span v-if="row.judge_cache_status">Judge {{ judgeCacheLabel(row.judge_cache_status) }}</span>
        </div>

        <div v-if="categoryList.length" class="category-list">
          <span v-for="category in categoryList" :key="category">
            {{ failureCategoryLabel(category) }}
          </span>
        </div>

        <div v-if="row.error" class="detail-error">{{ row.error }}</div>

        <section class="detail-section">
          <div class="section-title">评分拆解</div>
          <div class="score-breakdown">
            <div v-for="item in scoreCards" :key="item.key" class="score-card">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
          <div v-if="formulaText" class="score-formula">{{ formulaText }}</div>
          <div v-if="gapNotes.length" class="gap-list">
            <div v-for="item in gapNotes" :key="item" class="gap-note">{{ item }}</div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">期望</div>
          <div class="expect-grid">
            <div>
              <span>验收点</span>
              <ul v-if="expectedPoints.length">
                <li v-for="item in expectedPoints" :key="item">{{ item }}</li>
              </ul>
              <small v-else>-</small>
            </div>
            <div>
              <span>期望文档</span>
              <div v-if="expectedDocs.length" class="pill-list">
                <span v-for="item in expectedDocs" :key="item">{{ item }}</span>
              </div>
              <small v-else>-</small>
            </div>
            <div>
              <span>期望 chunk</span>
              <div v-if="expectedChunks.length" class="pill-list">
                <span v-for="item in expectedChunks" :key="item">{{ item }}</span>
              </div>
              <small v-else>-</small>
            </div>
          </div>
        </section>

        <section v-if="hitDetailGroups.length" class="detail-section">
          <div class="section-title">命中/缺失明细</div>
          <div class="hit-detail-grid">
            <div v-for="group in hitDetailGroups" :key="group.key" class="hit-detail-card">
              <header>{{ group.label }}</header>
              <div v-if="group.hits.length" class="hit-list">
                <span v-for="item in group.hits" :key="'hit-' + item" class="hit-pill">{{ item }}</span>
              </div>
              <small v-else>无命中</small>
              <template v-if="group.misses.length">
                <header class="miss-title">缺失</header>
                <div class="hit-list">
                  <span v-for="item in group.misses" :key="'miss-' + item" class="miss-pill">{{ item }}</span>
                </div>
              </template>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">回答与引用</div>
          <div class="answer-block" :class="{ empty: !row.actual_answer }">
            {{ row.actual_answer || '此模式没有生成回答' }}
          </div>
          <div v-if="citationRows.length" class="citation-list">
            <article v-for="(citation, idx) in citationRows" :key="idx" class="citation-item">
              <strong>{{ citation.title }}</strong>
              <span>{{ citation.meta }}</span>
            </article>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">检索结果</div>
          <div v-if="!resultRows.length" class="detail-empty compact">暂无检索结果</div>
          <div v-else class="result-table-wrap">
            <table>
              <thead>
                <tr>
                  <th class="col-rank">#</th>
                  <th class="col-source">来源</th>
                  <th class="col-location">位置</th>
                  <th class="col-score">分数</th>
                  <th class="col-preview">内容预览</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in resultRows" :key="item.key">
                  <td class="col-rank">{{ item.rank }}</td>
                  <td class="col-source">
                    <strong :title="item.title">{{ item.title }}</strong>
                    <small :title="item.chunkKey">{{ item.chunkKey }}</small>
                  </td>
                  <td class="col-location">{{ item.location }}</td>
                  <td class="col-score">{{ item.score }}</td>
                  <td class="col-preview">{{ item.preview }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="judgeRows.length || row.judge_error" class="detail-section">
          <div class="section-title">Judge</div>
          <div v-if="row.judge_error" class="detail-error compact">{{ row.judge_error }}</div>
          <dl class="kv-grid">
            <template v-for="item in judgeRows" :key="item.key">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </template>
          </dl>
        </section>

        <section v-if="traceRows.length" class="detail-section">
          <div class="section-title">Trace</div>
          <div class="trace-grid">
            <span v-for="item in traceRows" :key="item.key">
              {{ item.label }} <strong>{{ item.value }}</strong>
            </span>
          </div>
        </section>
      </div>
    </a-spin>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvalCaseDetailResponse } from '../../api/adminEval'
import {
  evalModeLabel,
  evalResultStatusLabel,
  evalTypeLabel,
  failureCategoryLabel,
  formatEvalMs,
  formatEvalScore,
  judgeCacheLabel,
} from '../../utils/evalLabels'
import { flavorLabel } from '../../utils/labelMaps'

type ObjectRow = Record<string, unknown>

const props = defineProps<{
  visible: boolean
  loading: boolean
  error: string
  detail: EvalCaseDetailResponse | null
}>()

const emit = defineEmits<{
  close: []
}>()

const row = computed(() => props.detail?.row ?? null)
const previewStatus = computed(() => props.detail?.preview?.status || (
  row.value?.error
    ? 'failed'
    : row.value?.verdict === 'not_applicable'
      ? 'not_applicable'
      : 'warning'
))
const previewLabel = computed(() => props.detail?.preview?.label || evalResultStatusLabel(previewStatus.value))
const expectedPoints = computed(() => listValue(row.value?.expected_points))
const expectedDocs = computed(() => listValue(row.value?.expected_docs?.length ? row.value.expected_docs : row.value?.expected_documents))
const expectedChunks = computed(() => listValue(row.value?.expected_chunk_keys))
const categoryList = computed(() => {
  const categories = listValue(row.value?.failure_categories)
  if (categories.length) return categories
  return row.value?.failure_category ? [String(row.value.failure_category)] : []
})
const displayFlavor = computed(() => {
  const value = row.value?.actual_retrieval_flavor || row.value?.preferred_flavor || ''
  return value ? flavorLabel(String(value)) : '-'
})
const citationRows = computed(() => listObjects(row.value?.actual_citations).map((item) => {
  const title = stringValue(item.file_title) || stringValue(item.document_title) || stringValue(item.document_id) || '未命名文档'
  const meta = [
    stringValue(item.section_title),
    item.page !== undefined && item.page !== null ? `第 ${item.page} 页` : '',
    stringValue(item.chunk_key),
  ].filter(Boolean).join(' / ') || '未标注位置'
  return { title, meta }
}))
const resultRows = computed(() => {
  const rows = listObjects(row.value?.rerank_results).length
    ? listObjects(row.value?.rerank_results)
    : listObjects(objectValue(row.value?.retrieval_step).results)
  return rows.slice(0, 20).map((item, idx) => normalizeResultRow(item, idx))
})
const judgeRows = computed(() => {
  const judge = objectValue(row.value?.judge)
  const rows = [
    { key: 'verdict', label: '结论', value: stringValue(judge.verdict || row.value?.verdict) },
    { key: 'judge_score', label: 'Judge分', value: scoreValue(judge.score ?? row.value?.judge_score) },
    { key: 'reason', label: '原因', value: stringValue(judge.reason) },
    { key: 'missing', label: '缺失验收点', value: joinValue(judge.missing_points) },
    { key: 'unsupported', label: '无依据声明', value: joinValue(judge.unsupported_claims) },
    { key: 'parse_warning', label: '解析警告', value: stringValue(judge.parse_warning) },
    { key: 'cache', label: 'Judge缓存', value: row.value?.judge_cache_status ? judgeCacheLabel(String(row.value.judge_cache_status)) : '' },
  ].filter((item) => item.value)
  return rows
})
const scoreCards = computed(() => {
  const r = row.value
  if (!r) return []
  const cards = [
    { key: 'final', label: '最终分', value: formatEvalScore(r.final_score) || '-' },
  ]
  if (r.eval_mode !== 'retrieval_only') {
    cards.push({ key: 'answer', label: '答案分', value: formatEvalScore(r.answer_score) || '-' })
    cards.push({ key: 'citation', label: '引用分', value: formatEvalScore(r.citation_score) || '-' })
    cards.push({ key: 'citations', label: '实际引用', value: String(citationRows.value.length) })
  }
  cards.push({ key: 'hit10', label: 'Hit@10', value: flagLabel(r.hit_at_10) })
  cards.push({ key: 'doc10', label: 'Doc@10', value: flagLabel(r.doc_hit_at_10) })
  cards.push({ key: 'chunk10', label: 'Chunk@10', value: flagLabel(r.chunk_hit_at_10) })
  if (typeof r.retrieval_latency_ms === 'number') {
    cards.push({ key: 'retrieval_latency', label: '检索耗时', value: formatEvalMs(r.retrieval_latency_ms) })
  }
  return cards
})
const formulaText = computed(() => {
  const r = row.value
  if (!r || r.eval_mode === 'retrieval_only' || r.eval_type === 'no_answer') return ''
  if (typeof r.answer_score !== 'number' || typeof r.citation_score !== 'number' || typeof r.final_score !== 'number') return ''
  return `评分公式：0.75 × 答案分 ${formatEvalScore(r.answer_score)} + 0.25 × 引用分 ${formatEvalScore(r.citation_score)} = ${formatEvalScore(r.final_score)}`
})
const gapNotes = computed(() => {
  const r = row.value
  if (!r) return []
  const notes: string[] = []
  if (r.eval_mode === 'retrieval_only') {
    if (r.hit_at_10 === true) notes.push('检索已在 Top10 内命中期望证据。')
    if (r.hit_at_10 === false) notes.push('检索 Top10 未命中期望文档或期望 chunk。')
    return notes
  }
  if (r.hit_at_10 === true && typeof r.citation_score === 'number' && r.citation_score < 1) {
    notes.push('检索已命中期望证据，但答案没有标注匹配期望文档的有效引用。')
  }
  if (citationRows.value.length === 0 && typeof r.citation_score === 'number' && r.citation_score < 1) {
    notes.push('回答中没有可识别的 [C#] 引用，因此引用分被扣。')
  }
  if (typeof r.answer_score === 'number' && r.answer_score < 0.8) {
    notes.push('答案内容未完全覆盖数值、关键词或验收点。')
  }
  if (r.eval_mode === 'full' && r.eval_type === 'llm_judge' && !objectValue(r.judge).verdict && r.final_score === null) {
    notes.push('完整模式未产生 Judge 评分，当前结果处于待评测状态。')
  }
  return notes
})
const hitDetailGroups = computed(() => {
  const r = row.value
  if (!r) return []
  return [
    {
      key: 'numeric',
      label: '数值',
      hits: listValue(r.numeric_hits),
      misses: listValue(r.numeric_misses),
    },
    {
      key: 'must',
      label: '必须命中',
      hits: listValue(r.must_hits),
      misses: listValue(r.must_miss),
    },
    {
      key: 'nice',
      label: '加分项',
      hits: listValue(r.nice_hits),
      misses: listValue(r.nice_miss),
    },
    {
      key: 'points',
      label: '验收点',
      hits: listValue(r.expected_point_hits),
      misses: listValue(r.expected_point_miss),
    },
    {
      key: 'citation',
      label: '引用文档',
      hits: listValue(r.citation_matched),
      misses: expectedDocs.value.filter((item) => !listValue(r.citation_matched).includes(item)),
    },
    {
      key: 'sections',
      label: '引用章节',
      hits: listValue(r.citation_section_matched),
      misses: listValue(r.citation_section_missed),
    },
    {
      key: 'forbidden',
      label: '拒答违规',
      hits: [],
      misses: listValue(r.forbidden_hits).concat(listValue(r.forbidden_phrase_hits)),
    },
  ].filter((group) => group.hits.length || group.misses.length)
})
const traceRows = computed(() => {
  const trace = objectValue(row.value?.trace)
  return Object.entries(trace)
    .filter(([key, value]) => isTraceMetric(key, value))
    .slice(0, 24)
    .map(([key, value]) => ({
      key,
      label: key,
      value: typeof value === 'number' ? formatEvalMs(value) : String(value),
    }))
})

function listValue(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item)).filter(Boolean)
}

function listObjects(value: unknown): ObjectRow[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ObjectRow => !!item && typeof item === 'object' && !Array.isArray(item))
}

function objectValue(value: unknown): ObjectRow {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ObjectRow : {}
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function joinValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean).join('；')
  return stringValue(value)
}

function scoreValue(value: unknown): string {
  return typeof value === 'number' ? value.toFixed(2) : stringValue(value)
}

function flagLabel(value: boolean | null | undefined): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '-'
}

function isTraceMetric(key: string, value: unknown): boolean {
  if (typeof value !== 'number' && typeof value !== 'string') return false
  return key.endsWith('_ms') || key.endsWith('ms') || key === 'total_ms' || key.includes('latency')
}

function normalizeResultRow(item: ObjectRow, index: number) {
  const rank = Number(item.rank ?? index + 1)
  const title = stringValue(item.file_title) || stringValue(item.document_title) || stringValue(item.document_id) || '未命名文档'
  const section = stringValue(item.section_title)
  const page = item.page !== undefined && item.page !== null ? `第 ${item.page} 页` : ''
  const location = [section, page].filter(Boolean).join(' / ') || '-'
  const score = typeof item.score === 'number' ? item.score.toFixed(4) : stringValue(item.score) || '-'
  const preview = stringValue(item.content_preview || item.text || item.content).slice(0, 260) || '-'
  const chunkKey = stringValue(item.chunk_key || item.chunk_id)
  return {
    key: `${rank}-${chunkKey}-${title}`,
    rank,
    title,
    chunkKey,
    location,
    score,
    preview,
  }
}
</script>

<style scoped>
.case-detail-spin {
  width: 100%;
}

.case-detail {
  display: grid;
  gap: 14px;
}

.detail-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
}

.detail-id {
  display: block;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 12px;
  margin-bottom: 4px;
}

.detail-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
  line-height: 1.35;
}

.detail-status {
  display: grid;
  justify-items: end;
  gap: 6px;
}

.detail-status strong {
  color: var(--text-primary);
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.status-pill {
  display: inline-flex;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 700;
}

.status-failed {
  background: #fee2e2;
  color: #991b1b;
}

.status-warning {
  background: #fef3c7;
  color: #92400e;
}

.status-not_applicable {
  background: #f1f5f9;
  color: #64748b;
}

.status-passed {
  background: #dcfce7;
  color: #166534;
}

.detail-metrics,
.category-list,
.trace-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.detail-metrics span,
.category-list span,
.trace-grid span {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 7px;
  background: #fbfdff;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.trace-grid strong {
  color: var(--text-primary);
}

.detail-section {
  display: grid;
  gap: 8px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.score-breakdown {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.score-card {
  display: grid;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: #fbfdff;
}

.score-card span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
}

.score-card strong {
  color: var(--text-primary);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.score-formula {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: var(--bg-soft);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.gap-list {
  display: grid;
  gap: 6px;
}

.gap-note {
  border-left: 3px solid #f59e0b;
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  background: #fffbeb;
  color: #92400e;
  font-size: 12px;
  line-height: 1.45;
}

.section-title {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
}

.expect-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
}

.expect-grid > div {
  display: grid;
  align-content: start;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: #fbfdff;
}

.expect-grid span {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.expect-grid ul {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
}

.expect-grid li,
.expect-grid small {
  color: var(--text-muted);
  font-size: 12px;
}

.pill-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.pill-list span {
  border-radius: 999px;
  padding: 2px 7px;
  background: var(--bg-hover);
  color: var(--text-secondary);
  font-size: 11px;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.hit-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
}

.hit-detail-card {
  display: grid;
  align-content: start;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: #fbfdff;
}

.hit-detail-card header {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.hit-detail-card small {
  color: var(--text-muted);
  font-size: 12px;
}

.miss-title {
  margin-top: 2px;
}

.hit-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.hit-pill,
.miss-pill {
  max-width: 100%;
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.hit-pill {
  background: #dcfce7;
  color: #166534;
}

.miss-pill {
  background: #fee2e2;
  color: #991b1b;
}

.answer-block {
  white-space: pre-wrap;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  background: #fbfdff;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.6;
}

.answer-block.empty {
  color: var(--text-muted);
}

.citation-list {
  display: grid;
  gap: 6px;
}

.citation-item {
  display: grid;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 7px 9px;
  background: #fff;
}

.citation-item strong {
  color: var(--text-primary);
  font-size: 12px;
}

.citation-item span {
  color: var(--text-muted);
  font-size: 11px;
}

.result-table-wrap {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

table {
  width: 100%;
  min-width: 860px;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}

th,
td {
  border-bottom: 1px solid var(--border-subtle);
  padding: 8px 9px;
  vertical-align: top;
}

th {
  background: var(--bg-soft);
  color: var(--text-secondary);
  font-weight: 700;
  text-align: left;
}

tbody tr:last-child td {
  border-bottom: 0;
}

.col-rank {
  width: 46px;
  text-align: center;
}

.col-source {
  width: 210px;
}

.col-source strong,
.col-source small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-source strong {
  color: var(--text-primary);
}

.col-source small {
  margin-top: 3px;
  color: var(--text-muted);
}

.col-location {
  width: 150px;
}

.col-score {
  width: 80px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.col-preview {
  color: var(--text-secondary);
  line-height: 1.45;
  word-break: break-word;
}

.kv-grid {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 7px 10px;
  margin: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 9px 10px;
  background: #fbfdff;
}

.kv-grid dt {
  color: var(--text-muted);
  font-size: 12px;
}

.kv-grid dd {
  margin: 0;
  color: var(--text-primary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.detail-error,
.detail-empty {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  color: var(--error);
  font-size: 12px;
}

.detail-empty {
  color: var(--text-muted);
}

.compact {
  padding: 8px 10px;
}

@media (max-width: 760px) {
  .detail-header,
  .expect-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-status {
    justify-items: start;
  }
}
</style>
