<template>
  <div v-if="authStore.isAdmin" class="eval-panel">
    <div class="eval-top">
      <div class="eval-header">
        <span class="eval-title">基准测试集回归</span>
        <span class="eval-status" :class="'status-' + status">{{ statusLabel }}</span>
        <span v-if="status === 'running' && evalTotal" class="eval-progress">
          {{ evalCurrent }} / {{ evalTotal }}<template v-if="evalCurrentId"> · {{ evalCurrentId }}</template>
        </span>
      </div>

      <div class="eval-actions">
        <a-button
          :type="status === 'running' ? 'secondary' : 'primary'"
          :loading="status === 'running'"
          :disabled="status === 'running' || estimatedRunCount <= 0"
          size="small"
          @click="onRun"
        >
          {{ buttonLabel }}
        </a-button>
      </div>
    </div>
    <div v-if="status !== 'running'" class="eval-run-config">
      <div class="option-grid option-grid-modes" role="radiogroup" aria-label="评测模式">
        <button
          v-for="option in RUN_MODE_OPTIONS"
          :key="option.value"
          type="button"
          class="option-card"
          :class="{ active: runMode === option.value }"
          @click="runMode = option.value"
        >
          <span>{{ option.title }}</span>
          <small>{{ option.desc }}</small>
        </button>
      </div>
      <div class="option-grid option-grid-scopes" role="radiogroup" aria-label="运行范围">
        <button
          v-for="option in RUN_SCOPE_OPTIONS"
          :key="option.value"
          type="button"
          class="option-card"
          :class="{ active: runScope === option.value }"
          :disabled="option.value === 'failed' && !hasFailedResults"
          @click="runScope = option.value"
        >
          <span>{{ option.title }}</span>
          <small>{{ option.desc }}</small>
        </button>
      </div>
      <div class="run-settings">
        <label v-if="runScope === 'flavor'" class="run-setting run-setting-select">
          <span>策略</span>
          <a-select v-model="runFlavor" size="small" class="run-flavor-select">
            <a-option v-for="mode in FLAVOR_KEYS" :key="mode" :value="mode">
              {{ flavorLabel(mode) }}
            </a-option>
          </a-select>
        </label>
        <label v-if="runScope === 'first_n'" class="run-setting">
          <span>数量</span>
          <a-input-number
            v-model="runLimit"
            size="small"
            :min="1"
            :max="enabledCount || 30"
            class="run-number-input"
          />
        </label>
        <label class="run-setting">
          <span>单题超时</span>
          <a-input-number
            v-model="caseTimeoutSec"
            size="small"
            :min="30"
            :max="600"
            :step="30"
            class="run-timeout-input"
          />
        </label>
        <label class="run-setting">
          <span>并发</span>
          <a-input-number
            v-model="runConcurrency"
            size="small"
            :min="0"
            :max="16"
            class="run-concurrency-input"
          />
        </label>
        <span
          class="run-estimate"
          :class="{ empty: estimatedRunCount <= 0, narrow: estimatedRunCount === 1 }"
          :title="estimatedRunCaseTitle"
        >
          预计 {{ estimatedRunCount }} 题
        </span>
        <label class="run-check">
          <input v-model="acceptBaseline" type="checkbox" />
          <span>设为基线</span>
        </label>
      </div>
    </div>
    <div v-if="status === 'running' && evalTotal" class="eval-progress-bar">
      <span :style="{ width: `${evalProgressPercent}%` }" />
    </div>

    <div v-if="summary && (status === 'succeeded' || status === 'failed')" class="eval-summary">
      <div class="sum-row">
        <span class="sum-item">模式 {{ evalModeLabel(summary.mode || runMode) }}</span>
        <span class="sum-item">策略 {{ summaryFlavorLabel(summary.flavor) }}</span>
        <span class="sum-item">题目 {{ summary.case_count ?? summary.overall.count }}</span>
        <span class="sum-item">已评分 {{ summary.scored_count ?? summary.overall.count }}</span>
        <span class="sum-item">未评分 {{ summary.unscored ?? 0 }}</span>
        <span class="sum-item">通过 {{ summary.passed ?? '-' }}</span>
        <span class="sum-item">警告 {{ summary.warning ?? '-' }}</span>
        <span class="sum-item">失败 {{ summary.failed ?? '-' }}</span>
        <span class="sum-item">均分 {{ percent(summary.overall.avg_score) }}</span>
        <span class="sum-item">评分通过 {{ percent(summary.overall.pass_rate) }}</span>
      </div>
      <div class="sum-row sum-row-secondary">
        <span class="sum-item">答案通过 {{ percent(summary.answer_pass_rate) }}</span>
        <span class="sum-item">Hit@5 {{ percent(summary.hit_at_5 ?? summary.overall.hit_at_5_rate) }}</span>
        <span class="sum-item">Hit@10 {{ percent(summary.hit_at_10 ?? summary.overall.hit_at_10_rate) }}</span>
        <span class="sum-item">引用命中 {{ percent(summary.citation_hit_rate) }}</span>
        <span class="sum-item">P50 {{ ms(summary.latency_p50_ms ?? summary.overall.p50_latency_ms) }}</span>
        <span class="sum-item">P95 {{ ms(summary.latency_p95_ms ?? summary.overall.p95_latency_ms) }}</span>
        <span class="sum-item">超时 {{ summary.timeout_count ?? 0 }}</span>
        <span v-if="summary.judge_cache?.checked" class="sum-item">
          Judge缓存 {{ judgeCacheSummary(summary.judge_cache) }}
        </span>
        <span v-if="summary.baseline_delta" class="sum-item">
          基线 {{ baselineDeltaSummary(summary.baseline_delta.overall) }}
        </span>
        <span v-else-if="summary.baseline && !summary.baseline.available" class="sum-item">
          基线 -
        </span>
      </div>
      <div v-if="currentResultPath || currentSummaryPath" class="eval-output-paths">
        <span v-if="currentResultPath">结果 {{ currentResultPath }}</span>
        <span v-if="currentSummaryPath">摘要 {{ currentSummaryPath }}</span>
      </div>

      <div v-if="failureCategoryRows.length" class="failure-breakdown">
        <span v-for="row in failureCategoryRows" :key="row.key">
          {{ row.label }} {{ row.count }}
        </span>
      </div>

      <div v-if="flavorRows.length" class="flavor-breakdown">
        <div class="breakdown-title">按策略</div>
        <div class="breakdown-grid">
          <div v-for="row in flavorRows" :key="row.key" class="breakdown-card">
            <span>{{ row.label }}</span>
            <strong>{{ row.metric.count }}</strong>
            <small>均分 {{ percent(row.metric.avg_score) }} / 通过 {{ percent(row.metric.pass_rate) }}</small>
            <small>Hit@5 {{ percent(row.metric.hit_at_5_rate) }} / Hit@10 {{ percent(row.metric.hit_at_10_rate) }}</small>
          </div>
        </div>
      </div>

      <div v-if="summary.per_strict" class="strict-breakdown">
        仅基于资料回答：{{ summary.per_strict.count }} 题，
        均分 {{ percent(summary.per_strict.avg_score) }}，
        通过 {{ percent(summary.per_strict.pass_rate) }}
      </div>
    </div>

    <div v-if="status === 'failed' && error" class="eval-error">{{ error }}</div>

    <EvalCaseTable
      v-if="showCaseDiagnostics"
      :cases="evalResults"
      @open="openEvalCaseDetail"
    />
    <EvalCaseDetailDrawer
      :visible="caseDetailOpen"
      :loading="caseDetailLoading"
      :error="caseDetailError"
      :detail="caseDetail"
      @close="caseDetailOpen = false"
    />

    <div class="golden-list">
      <div class="golden-list-head">
        <span>当前基准测试集</span>
        <small v-if="goldenSetPath">{{ goldenSetPath }}</small>
        <strong>{{ enabledCount }} / {{ goldenCases.length }} 启用</strong>
      </div>
      <div v-if="goldenLoading" class="golden-empty">加载中...</div>
      <div v-else-if="goldenError" class="golden-empty error">{{ goldenError }}</div>
      <div v-else :ref="setGoldenTableContainer" class="golden-table-wrap">
        <table class="golden-table">
          <colgroup>
            <col :style="columnStyle('id')" />
            <col :style="columnStyle('result')" />
            <col :style="columnStyle('question')" />
            <col :style="columnStyle('flavor')" />
            <col :style="columnStyle('set')" />
            <col :style="columnStyle('strict')" />
            <col :style="columnStyle('rule')" />
            <col :style="columnStyle('points')" />
            <col :style="columnStyle('docs')" />
            <col :style="columnStyle('enabled')" />
            <col :style="columnStyle('actions')" />
          </colgroup>
          <thead>
            <tr>
              <th class="col-id resizable-th">ID<span class="resize-handle" @mousedown="goldenColumns.startResize('id', $event)" /></th>
              <th class="col-result resizable-th">结果<span class="resize-handle" @mousedown="goldenColumns.startResize('result', $event)" /></th>
              <th class="col-question resizable-th">问题<span class="resize-handle" @mousedown="goldenColumns.startResize('question', $event)" /></th>
              <th class="col-flavor resizable-th">策略<span class="resize-handle" @mousedown="goldenColumns.startResize('flavor', $event)" /></th>
              <th class="col-set resizable-th">集合<span class="resize-handle" @mousedown="goldenColumns.startResize('set', $event)" /></th>
              <th class="col-strict resizable-th">仅资料<span class="resize-handle" @mousedown="goldenColumns.startResize('strict', $event)" /></th>
              <th class="col-rule resizable-th">评测<span class="resize-handle" @mousedown="goldenColumns.startResize('rule', $event)" /></th>
              <th class="col-count resizable-th">验收点<span class="resize-handle" @mousedown="goldenColumns.startResize('points', $event)" /></th>
              <th class="col-count resizable-th">文档<span class="resize-handle" @mousedown="goldenColumns.startResize('docs', $event)" /></th>
              <th class="col-enabled resizable-th">状态<span class="resize-handle" @mousedown="goldenColumns.startResize('enabled', $event)" /></th>
              <th class="col-actions resizable-th">操作<span class="resize-handle" @mousedown="goldenColumns.startResize('actions', $event)" /></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in goldenCases" :key="item.id || item.question" :class="{ disabled: !caseEnabled(item) }">
              <td class="col-id">{{ item.id }}</td>
              <td class="col-result">
                <span class="result-badge" :class="'result-' + caseResult(item.id).status">
                  {{ caseResult(item.id).label }}
                </span>
                <small v-if="caseResult(item.id).score !== null && caseResult(item.id).score !== undefined">
                  {{ formatScore(caseResult(item.id).score) }}
                </small>
                <small
                  v-if="caseResult(item.id).status === 'failed' && caseResult(item.id).failure_category"
                  class="result-failure-tag"
                >
                  {{ failureCategoryLabel(caseResult(item.id).failure_category || '') }}
                </small>
                <small v-if="caseResult(item.id).judge_cache_status" class="result-cache-tag">
                  {{ judgeCacheLabel(caseResult(item.id).judge_cache_status || '') }}
                </small>
              </td>
              <td class="question-cell">{{ item.question }}</td>
              <td class="col-flavor">{{ flavorLabel(item.preferred_flavor) }}</td>
              <td class="col-set">
                <span v-if="item.quick" class="smoke-badge">冒烟</span>
                <span v-else class="muted-cell">-</span>
              </td>
              <td class="col-strict">{{ item.strict_evidence ? '是' : '否' }}</td>
              <td class="col-rule">{{ evalTypeLabel(item.eval_type) }}</td>
              <td class="col-count">{{ item.expected_points_count }}</td>
              <td class="col-count">{{ item.expected_documents.length }}</td>
              <td class="col-enabled">
                <span class="enabled-badge" :class="caseEnabled(item) ? 'enabled-on' : 'enabled-off'">
                  {{ caseEnabled(item) ? '启用' : '停用' }}
                </span>
              </td>
              <td class="col-actions">
                <a-button
                  size="mini"
                  :disabled="status === 'running'"
                  @click="openGoldenCaseEditor(item)"
                >
                  编辑
                </a-button>
                <a-button
                  size="mini"
                  :disabled="status === 'running'"
                  :loading="togglingIds.has(item.id)"
                  @click="toggleGoldenCase(item)"
                >
                  {{ caseEnabled(item) ? '停用' : '启用' }}
                </a-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="draft-list">
      <div class="golden-list-head">
        <span>基准测试集草稿</span>
        <small v-if="draftPath">{{ draftPath }}</small>
        <strong>{{ drafts.length }} 条</strong>
      </div>
      <div v-if="draftLoading" class="golden-empty">加载中...</div>
      <div v-else-if="draftError" class="golden-empty error">{{ draftError }}</div>
      <div v-else-if="!drafts.length" class="golden-empty">暂无草稿。可在答案反馈中加入草稿。</div>
      <div v-else class="draft-rows">
        <article v-for="draft in drafts" :key="draft.id" class="draft-row">
          <strong :title="draft.question">{{ draft.question }}</strong>
          <span>{{ flavorLabel(draft.preferred_flavor) }}</span>
          <span>{{ draft.strict_evidence ? '仅资料' : '普通回答' }}</span>
          <span>{{ (draft.expected_points || []).length }} 验收点</span>
          <span>#{{ draft.source_feedback_id }}</span>
          <div class="draft-actions">
            <a-button size="mini" @click="openDraftEditor(draft)">编辑</a-button>
            <a-button
              size="mini"
              type="primary"
              :loading="publishingIds.has(draft.id)"
              @click="publishDraft(draft)"
            >
              发布
            </a-button>
            <a-popconfirm content="删除这条基准测试集草稿？" @ok="deleteDraft(draft)">
              <a-button size="mini" status="danger" :loading="deletingIds.has(draft.id)">删除</a-button>
            </a-popconfirm>
          </div>
        </article>
      </div>
    </div>

    <a-modal
      v-model:visible="draftEditorOpen"
      :title="editorTitle"
      :width="720"
      :ok-loading="draftSaving"
      ok-text="保存"
      cancel-text="取消"
      @ok="saveEditor"
    >
      <div class="draft-form">
        <label>
          <span>问题</span>
          <a-textarea v-model="draftForm.question" :auto-size="{ minRows: 2, maxRows: 4 }" />
        </label>
        <div class="case-config-panel">
          <div class="config-line config-line-strategy">
            <label class="config-field">
              <span class="config-field-head">
                <span>策略</span>
                <span class="metadata-check">
                  <input v-model="draftForm.strict_evidence" type="checkbox" />
                  <span>仅资料</span>
                </span>
              </span>
              <div class="segmented-control flavor-segments" role="radiogroup" aria-label="策略">
                <button
                  v-for="mode in FLAVOR_KEYS"
                  :key="mode"
                  type="button"
                  :class="{ active: draftForm.preferred_flavor === mode }"
                  @click="draftForm.preferred_flavor = mode"
                >
                  {{ flavorLabel(mode) }}
                </button>
              </div>
            </label>
          </div>
          <div class="config-line config-line-eval">
            <label class="config-field">
              <span>评测</span>
              <div class="segmented-control eval-segments" role="radiogroup" aria-label="评测">
                <button
                  v-for="option in EVAL_TYPE_OPTIONS"
                  :key="option.value"
                  type="button"
                  :class="{ active: draftForm.eval_type === option.value }"
                  @click="draftForm.eval_type = option.value"
                >
                  {{ option.label }}
                </button>
              </div>
            </label>
            <label class="config-field min-citations-control">
              <span>最少引用</span>
              <a-input-number
                v-model="draftForm.min_expected_citations"
                class="min-citations-input"
                :min="1"
                :max="10"
              />
            </label>
          </div>
        </div>
        <label>
          <span>验收点（每行一条，发布前至少 1 条）</span>
          <a-textarea v-model="draftPointsText" :auto-size="{ minRows: 3, maxRows: 6 }" />
        </label>
        <label>
          <span>期望文档（每行一个文件名或文档 ID，可选）</span>
          <a-textarea v-model="draftDocsText" :auto-size="{ minRows: 2, maxRows: 4 }" />
        </label>
        <label>
          <span>参考答案（可选）</span>
          <a-textarea v-model="draftForm.expected_answer" :auto-size="{ minRows: 2, maxRows: 5 }" />
        </label>
        <label v-if="editorMode === 'draft'">
          <span>备注</span>
          <a-input v-model="draftForm.notes" allow-clear />
        </label>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, type ComponentPublicInstance } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'
import {
  getEvalCaseResult,
  getEvalStatus,
  getGoldenSet,
  runEval,
  setGoldenCaseEnabled,
  updateGoldenCase,
  type EvalBaselineDelta,
  type EvalCaseDetailResponse,
  type EvalCaseResult,
  type EvalMetricDelta,
  type GoldenCaseUpdate,
  type EvalRunOptions,
  type EvalSummary,
  type GoldenSetCase,
} from '../../api/adminEval'
import {
  deleteGoldenDraft,
  listGoldenDrafts,
  publishGoldenDraft,
  updateGoldenDraft,
  type GoldenDraft,
  type GoldenDraftUpdate,
} from '../../api/queryFeedback'
import { useAutoFitColumns } from '../../composables/useAutoFitColumns'
import {
  evalModeLabel,
  evalTypeLabel,
  failureCategoryLabel,
  formatEvalMs as ms,
  formatEvalScore as formatScore,
  judgeCacheLabel,
} from '../../utils/evalLabels'
import { FLAVOR_KEYS, flavorLabel } from '../../utils/labelMaps'
import EvalCaseDetailDrawer from './EvalCaseDetailDrawer.vue'
import EvalCaseTable from './EvalCaseTable.vue'

const authStore = useAuthStore()
const status = ref('idle')
const summary = ref<EvalSummary | null>(null)
const error = ref('')
const goldenCases = ref<GoldenSetCase[]>([])
const goldenSetPath = ref('')
const goldenLoading = ref(false)
const goldenError = ref('')
const drafts = ref<GoldenDraft[]>([])
const draftPath = ref('')
const draftLoading = ref(false)
const draftError = ref('')
const draftEditorOpen = ref(false)
const draftSaving = ref(false)
const editorMode = ref<'draft' | 'case'>('draft')
const editingDraftId = ref('')
const editingCaseId = ref('')
const draftPointsText = ref('')
const draftDocsText = ref('')
const publishingIds = ref<Set<string>>(new Set())
const deletingIds = ref<Set<string>>(new Set())
const togglingIds = ref<Set<string>>(new Set())
const evalTotal = ref(0)
const evalCurrent = ref(0)
const evalCurrentId = ref('')
const evalResults = ref<EvalCaseResult[]>([])
const resultPath = ref('')
const summaryPath = ref('')
const caseDetailOpen = ref(false)
const caseDetailLoading = ref(false)
const caseDetailError = ref('')
const caseDetail = ref<EvalCaseDetailResponse | null>(null)
type EvalRunMode = 'full' | 'retrieval_only' | 'answer_lite'
type EvalRunScope = 'all' | 'smoke' | 'failed' | 'flavor' | 'first_n'

const runMode = ref<EvalRunMode>('full')
const runScope = ref<EvalRunScope>('all')
const runFlavor = ref('balanced')
const runLimit = ref(5)
const caseTimeoutSec = ref(180)
const runConcurrency = ref(0)
const acceptBaseline = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null
let pollFailCount = 0

const POLL_BASE_MS = 2000
const POLL_MAX_MS = 10000
const MAX_POLL_FAILS = 5
const goldenColumns = useAutoFitColumns('enterprise-rag:eval-golden-set:auto-v2', {
  id: { width: 130, minWidth: 90, maxWidth: 190 },
  result: { width: 63, minWidth: 56, maxWidth: 90 },
  question: { width: 360, minWidth: 260, flex: true },
  flavor: { width: 70, minWidth: 60, maxWidth: 100 },
  set: { width: 58, minWidth: 52, maxWidth: 80 },
  strict: { width: 60, minWidth: 52, maxWidth: 80 },
  rule: { width: 60, minWidth: 52, maxWidth: 80 },
  points: { width: 60, minWidth: 52, maxWidth: 80 },
  docs: { width: 60, minWidth: 52, maxWidth: 80 },
  enabled: { width: 64, minWidth: 56, maxWidth: 80 },
  actions: { width: 112, minWidth: 96, maxWidth: 150 },
}, { minWidth: 52 })

const draftForm = ref<GoldenDraftUpdate>(emptyDraftForm())

const STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
}

const BUTTON_LABELS: Record<string, string> = {
  idle: '运行基准测试集',
  running: '评估运行中',
  succeeded: '重新运行',
  failed: '重试评估',
}

const EVAL_TYPE_OPTIONS = [
  { value: 'llm_judge', label: 'LLM' },
  { value: 'rule', label: '规则' },
  { value: 'no_answer', label: '拒答' },
] as const

const RUN_MODE_OPTIONS: Array<{ value: EvalRunMode; title: string; desc: string }> = [
  { value: 'retrieval_only', title: '仅检索', desc: '只测召回与 Hit@K' },
  { value: 'answer_lite', title: '轻答案', desc: '生成答案，轻量评分' },
  { value: 'full', title: '完整', desc: '完整链路，Judge评分' },
]

const RUN_SCOPE_OPTIONS: Array<{ value: EvalRunScope; title: string; desc: string }> = [
  { value: 'all', title: '全部启用', desc: '运行当前启用用例' },
  { value: 'smoke', title: '冒烟集', desc: '只跑精选用例' },
  { value: 'failed', title: '失败重跑', desc: '只重跑上次失败' },
  { value: 'flavor', title: '按策略', desc: '限定检索策略' },
  { value: 'first_n', title: '前 N 条', desc: '跑前几个用例' },
]

const statusLabel = computed(() => STATUS_LABELS[status.value] ?? status.value)
const buttonLabel = computed(() => BUTTON_LABELS[status.value] ?? '运行')
const editorTitle = computed(() => editorMode.value === 'case' ? '编辑基准测试用例' : '编辑基准测试集草稿')
const resultById = computed(() => {
  return Object.fromEntries(evalResults.value.map((item) => [item.id, item] as const))
})

const flavorRows = computed(() => {
  const data = summary.value?.per_flavor
  if (!data) return []
  return FLAVOR_KEYS
    .filter((key) => data[key])
    .map((key) => ({ key, label: flavorLabel(key), metric: data[key] }))
})
const failureCategoryRows = computed(() => {
  const data = summary.value?.failure_categories
  if (!data) return []
  return Object.entries(data)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => ({ key, label: failureCategoryLabel(key), count }))
})
const enabledCount = computed(() => goldenCases.value.filter(caseEnabled).length)
const evalProgressPercent = computed(() => {
  if (!evalTotal.value) return 0
  return Math.min(100, Math.max(0, (evalCurrent.value / evalTotal.value) * 100))
})
const currentResultPath = computed(() => summary.value?.output_path || resultPath.value)
const currentSummaryPath = computed(() => summary.value?.summary_path || summaryPath.value)
const showCaseDiagnostics = computed(() => {
  return evalResults.value.some((item) => item.status === 'failed' || item.status === 'warning')
})
const hasFailedResults = computed(() => evalResults.value.some((item) => item.status === 'failed'))
const estimatedRunCases = computed(() => {
  let selected = goldenCases.value.filter(caseEnabled)
  if (runScope.value === 'smoke') {
    selected = selected.filter((item) => item.quick)
  } else if (runScope.value === 'failed') {
    const failedIds = new Set(evalResults.value
      .filter((item) => item.status === 'failed')
      .map((item) => item.id)
      .filter(Boolean))
    selected = selected.filter((item) => failedIds.has(item.id))
  } else if (runScope.value === 'flavor') {
    selected = selected.filter((item) => item.preferred_flavor === runFlavor.value)
  }
  if (runScope.value === 'first_n') {
    selected = selected.slice(0, Math.max(0, runLimit.value || 0))
  }
  return selected
})
const estimatedRunCount = computed(() => estimatedRunCases.value.length)
const estimatedRunCaseTitle = computed(() => {
  const ids = estimatedRunCases.value.map((item) => item.id).filter(Boolean)
  return ids.length ? ids.join(', ') : '无匹配用例'
})

function emptyDraftForm(): GoldenDraftUpdate {
  return {
    question: '',
    preferred_flavor: 'balanced',
    strict_evidence: false,
    eval_type: 'llm_judge',
    expected_answer: '',
    expected_points: [],
    expected_documents: [],
    min_expected_citations: 1,
    notes: '',
  }
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function columnStyle(key: string) {
  const width = goldenColumns.columnWidth(key)
  return width ? { width: `${width}px` } : {}
}

function setGoldenTableContainer(element: Element | ComponentPublicInstance | null) {
  goldenColumns.containerRef.value = element instanceof HTMLElement ? element : null
}

function caseResult(id: string): EvalCaseResult {
  return resultById.value[id] ?? {
    id,
    question: '',
    status: status.value === 'running' ? 'queued' : 'queued',
    label: status.value === 'running' ? '等待' : '-',
    score: null,
    error: '',
  }
}

function caseEnabled(item: GoldenSetCase): boolean {
  return item.enabled !== false && item.status !== 'disabled'
}

function judgeCacheSummary(cache: EvalSummary['judge_cache']): string {
  if (!cache) return '-'
  const parts: string[] = []
  if (cache.score?.checked) parts.push(`评分 ${cache.score.hits}/${cache.score.checked}`)
  if (cache.lookup_only?.checked) parts.push(`只查 ${cache.lookup_only.hits}/${cache.lookup_only.checked}`)
  return parts.length ? parts.join(' · ') : `${cache.hits}/${cache.checked}`
}

function baselineDeltaSummary(delta: EvalBaselineDelta['overall']): string {
  if (!delta) return '-'
  const parts = [
    baselineMetricDelta('Hit@10', delta.hit_at_10, true),
    baselineMetricDelta('引用', delta.citation_hit_rate, true),
    baselineMetricDelta('答案', delta.answer_pass_rate, true),
    baselineMetricDelta('P95', delta.p95_latency_ms, false, 'ms'),
    baselineMetricDelta('超时', delta.timeout_count, false),
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : '-'
}

function baselineMetricDelta(
  label: string,
  item: EvalMetricDelta | undefined,
  asPercent: boolean,
  suffix = '',
): string {
  const value = item?.delta
  if (value === null || value === undefined) return ''
  const signed = value > 0 ? '+' : ''
  if (asPercent) return `${label} ${signed}${(value * 100).toFixed(1)}pp`
  return `${label} ${signed}${Math.round(value)}${suffix}`
}

function summaryFlavorLabel(value: string | undefined): string {
  if (!value) return '-'
  if (value === 'mixed') return '混合'
  return flavorLabel(value)
}

async function refresh(): Promise<boolean> {
  try {
    const s = await getEvalStatus()
    status.value = s.status
    summary.value = s.summary
    error.value = s.error
    resultPath.value = s.result_path || s.summary?.output_path || ''
    summaryPath.value = s.summary_path || s.summary?.summary_path || ''
    evalTotal.value = s.total ?? 0
    evalCurrent.value = s.current ?? 0
    evalCurrentId.value = s.current_id ?? ''
    evalResults.value = s.results_preview ?? []
    if (s.mode === 'quick') {
      runMode.value = 'full'
      runScope.value = 'smoke'
    } else if (s.mode === 'full' || s.mode === 'retrieval_only' || s.mode === 'answer_lite') {
      runMode.value = s.mode
    }
    pollFailCount = 0
    return true
  } catch {
    pollFailCount += 1
    if (status.value === 'running' && pollFailCount >= MAX_POLL_FAILS) {
      status.value = 'failed'
      error.value = '评估状态查询失败，请稍后重试'
    }
    return false
  }
}

async function onRun() {
  const options = buildRunOptions()
  if (!options) return
  clearPoll()
  status.value = 'running'
  summary.value = null
  error.value = ''
  resultPath.value = ''
  summaryPath.value = ''
  evalCurrent.value = 0
  evalCurrentId.value = ''
  evalResults.value = []
  caseDetailOpen.value = false
  caseDetail.value = null
  caseDetailError.value = ''
  pollFailCount = 0
  try {
    await runEval(options)
    await refresh()
    schedulePoll()
  } catch (e: any) {
    status.value = 'failed'
    error.value = e?.response?.data?.detail || '评估启动失败'
    Message.error(error.value)
  }
}

async function openEvalCaseDetail(item: EvalCaseResult) {
  if (!item.id) return
  caseDetailOpen.value = true
  caseDetailLoading.value = true
  caseDetailError.value = ''
  try {
    caseDetail.value = await getEvalCaseResult(item.id)
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '评测用例详情加载失败'
    caseDetail.value = null
    caseDetailError.value = detail
    Message.error(detail)
  } finally {
    caseDetailLoading.value = false
  }
}

function buildRunOptions(): EvalRunOptions | null {
  if (estimatedRunCount.value <= 0) {
    Message.warning('当前选择没有可运行用例')
    return null
  }
  const options: EvalRunOptions = {
    mode: runMode.value,
    judge: runMode.value === 'full',
    case_timeout_sec: caseTimeoutSec.value,
    concurrency: runConcurrency.value,
    accept_baseline: acceptBaseline.value,
  }
  if (runScope.value === 'smoke') {
    options.case_ids = estimatedRunCases.value.map((item) => item.id).filter(Boolean)
  } else if (runScope.value === 'failed') {
    const failedIds = evalResults.value
      .filter((item) => item.status === 'failed')
      .map((item) => item.id)
      .filter(Boolean)
    if (!failedIds.length) {
      Message.warning('当前没有失败用例可重跑')
      return null
    }
    options.case_ids = failedIds
  } else if (runScope.value === 'flavor') {
    options.flavor = runFlavor.value
  } else if (runScope.value === 'first_n') {
    options.limit = runLimit.value
  }
  return options
}

function schedulePoll() {
  clearPoll()
  if (status.value !== 'running') return
  const delay = Math.min(POLL_BASE_MS * Math.max(1, pollFailCount + 1), POLL_MAX_MS)
  timer = setTimeout(async () => {
    await refresh()
    schedulePoll()
  }, delay)
}

function clearPoll() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

async function loadGoldenSet() {
  goldenLoading.value = true
  goldenError.value = ''
  try {
    const res = await getGoldenSet()
    goldenCases.value = res.cases
    goldenSetPath.value = res.path
  } catch (e: any) {
    goldenError.value = e?.response?.data?.detail || '基准测试集加载失败'
  } finally {
    goldenLoading.value = false
  }
}

async function loadDrafts() {
  draftLoading.value = true
  draftError.value = ''
  try {
    const res = await listGoldenDrafts()
    drafts.value = res.drafts
    draftPath.value = res.path
  } catch (e: any) {
    draftError.value = e?.response?.data?.detail || '基准测试集草稿加载失败'
  } finally {
    draftLoading.value = false
  }
}

function openDraftEditor(draft: GoldenDraft) {
  editorMode.value = 'draft'
  editingDraftId.value = draft.id
  editingCaseId.value = ''
  draftForm.value = {
    question: draft.question || '',
    preferred_flavor: draft.preferred_flavor || 'balanced',
    strict_evidence: Boolean(draft.strict_evidence),
    eval_type: draft.eval_type || 'llm_judge',
    expected_answer: draft.expected_answer || '',
    expected_points: draft.expected_points || [],
    expected_documents: draft.expected_documents || [],
    min_expected_citations: draft.min_expected_citations ?? 1,
    notes: draft.notes || '',
  }
  draftPointsText.value = (draft.expected_points || []).join('\n')
  draftDocsText.value = (draft.expected_documents || []).join('\n')
  draftEditorOpen.value = true
}

function openGoldenCaseEditor(item: GoldenSetCase) {
  editorMode.value = 'case'
  editingDraftId.value = ''
  editingCaseId.value = item.id
  draftForm.value = {
    question: item.question || '',
    preferred_flavor: item.preferred_flavor || 'balanced',
    strict_evidence: Boolean(item.strict_evidence),
    eval_type: item.eval_type || 'llm_judge',
    expected_answer: item.expected_answer || '',
    expected_points: item.expected_points || [],
    expected_documents: item.expected_documents || [],
    min_expected_citations: item.min_expected_citations ?? 1,
    notes: '',
  }
  draftPointsText.value = (item.expected_points || []).join('\n')
  draftDocsText.value = (item.expected_documents || []).join('\n')
  draftEditorOpen.value = true
}

function listFromText(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function draftPayload(): GoldenDraftUpdate {
  return {
    ...draftForm.value,
    expected_points: listFromText(draftPointsText.value),
    expected_documents: listFromText(draftDocsText.value),
    min_expected_citations: Number(draftForm.value.min_expected_citations || 0),
  }
}

function goldenCasePayload(): GoldenCaseUpdate {
  return {
    question: draftForm.value.question,
    preferred_flavor: draftForm.value.preferred_flavor,
    strict_evidence: draftForm.value.strict_evidence,
    eval_type: draftForm.value.eval_type,
    expected_answer: draftForm.value.expected_answer,
    expected_points: listFromText(draftPointsText.value),
    expected_documents: listFromText(draftDocsText.value),
    min_expected_citations: Number(draftForm.value.min_expected_citations || 0),
  }
}

async function saveEditor() {
  if (editorMode.value === 'case') {
    await saveGoldenCase()
  } else {
    await saveDraft()
  }
}

async function saveDraft() {
  if (!editingDraftId.value) return
  const payload = draftPayload()
  if (!payload.question.trim()) {
    Message.warning('请填写问题')
    return
  }
  draftSaving.value = true
  try {
    const res = await updateGoldenDraft(editingDraftId.value, payload)
    drafts.value = drafts.value.map((item) => item.id === res.draft.id ? res.draft : item)
    draftEditorOpen.value = false
    Message.success('草稿已保存')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '草稿保存失败')
  } finally {
    draftSaving.value = false
  }
}

async function saveGoldenCase() {
  if (!editingCaseId.value) return
  const payload = goldenCasePayload()
  if (!payload.question.trim()) {
    Message.warning('请填写问题')
    return
  }
  draftSaving.value = true
  try {
    const res = await updateGoldenCase(editingCaseId.value, payload)
    goldenCases.value = goldenCases.value.map((item) => item.id === res.case.id ? res.case : item)
    goldenSetPath.value = res.path
    draftEditorOpen.value = false
    Message.success('基准测试用例已保存')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '基准测试用例保存失败')
  } finally {
    draftSaving.value = false
  }
}

async function deleteDraft(draft: GoldenDraft) {
  deletingIds.value = new Set([...deletingIds.value, draft.id])
  try {
    await deleteGoldenDraft(draft.id)
    drafts.value = drafts.value.filter((item) => item.id !== draft.id)
    Message.success('草稿已删除')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '草稿删除失败')
  } finally {
    const next = new Set(deletingIds.value)
    next.delete(draft.id)
    deletingIds.value = next
  }
}

async function publishDraft(draft: GoldenDraft) {
  if (!(draft.expected_points || []).length) {
    Message.warning('发布前至少填写一个验收点')
    openDraftEditor(draft)
    return
  }
  publishingIds.value = new Set([...publishingIds.value, draft.id])
  try {
    await publishGoldenDraft(draft.id)
    drafts.value = drafts.value.filter((item) => item.id !== draft.id)
    await loadGoldenSet()
    Message.success('已发布到基准测试集')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '发布失败')
  } finally {
    const next = new Set(publishingIds.value)
    next.delete(draft.id)
    publishingIds.value = next
  }
}

async function toggleGoldenCase(item: GoldenSetCase) {
  const nextEnabled = !caseEnabled(item)
  togglingIds.value = new Set([...togglingIds.value, item.id])
  try {
    const res = await setGoldenCaseEnabled(item.id, nextEnabled)
    goldenCases.value = goldenCases.value.map((row) => row.id === item.id ? res.case : row)
    Message.success(nextEnabled ? '已启用' : '已停用')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '状态更新失败')
  } finally {
    const next = new Set(togglingIds.value)
    next.delete(item.id)
    togglingIds.value = next
  }
}

onMounted(async () => {
  await Promise.all([refresh(), loadGoldenSet(), loadDrafts()])
  schedulePoll()
})

onUnmounted(clearPoll)
</script>

<style scoped>
.eval-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px 18px;
  margin-top: 16px;
}

.eval-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.eval-header {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 10px;
}

.eval-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

.eval-status {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
}

.eval-progress {
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.eval-progress-bar {
  height: 3px;
  margin: -2px 0 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-hover);
}

.eval-progress-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width 0.2s ease;
}

.eval-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.eval-run-config {
  display: grid;
  gap: 8px;
  margin-bottom: 10px;
}

.option-grid {
  display: grid;
  gap: 8px;
}

.option-grid-modes {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.option-grid-scopes {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.option-card {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 52px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: #fff;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.option-card:hover:not(:disabled) {
  border-color: #93c5fd;
  background: #f8fbff;
}

.option-card.active {
  border-color: var(--accent);
  background: #eff6ff;
  color: var(--accent);
}

.option-card:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.option-card span {
  overflow: hidden;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-card small {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-settings {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  min-height: 30px;
  padding-top: 2px;
}

.run-setting,
.run-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.run-setting-select {
  min-width: 156px;
}

.run-flavor-select {
  width: 108px;
}

.run-number-input {
  width: 76px;
}

.run-timeout-input {
  width: 84px;
}

.run-concurrency-input {
  width: 72px;
}

.run-check input {
  margin: 0;
}

.run-estimate {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 8px;
  background: #fbfdff;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.run-estimate.narrow {
  border-color: #fde68a;
  background: #fffbeb;
  color: #92400e;
}

.run-estimate.empty {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}

.status-idle { color: var(--text-muted); background: var(--bg-hover); }
.status-running { color: #1e40af; background: #dbeafe; }
.status-succeeded { color: #166534; background: #dcfce7; }
.status-failed { color: #991b1b; background: #fee2e2; }

.eval-summary {
  margin-top: 10px;
}

.sum-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px 12px;
}

.sum-row-secondary {
  margin-top: 6px;
}

.sum-item {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.sum-row-secondary .sum-item {
  color: var(--text-muted);
}

.eval-output-paths {
  display: grid;
  gap: 3px;
  margin-top: 8px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.failure-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.failure-breakdown span {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 2px 7px;
  background: #fbfdff;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.flavor-breakdown {
  margin-top: 12px;
}

.breakdown-title {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}

.breakdown-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 8px;
}

.breakdown-card {
  display: grid;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: #fbfdff;
}

.breakdown-card span {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}

.breakdown-card strong {
  font-size: 18px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.breakdown-card small,
.strict-breakdown {
  color: var(--text-muted);
  font-size: 11px;
}

.strict-breakdown {
  margin-top: 10px;
}

.eval-error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--error);
}

.golden-list {
  margin-top: 14px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.draft-list {
  margin-top: 12px;
  border-top: 1px solid var(--border);
  padding-top: 10px;
}

.draft-rows {
  display: grid;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.draft-row {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 82px 82px 76px 56px auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  background: #fbfdff;
  border-bottom: 1px solid var(--border-subtle);
}

.draft-row:last-child {
  border-bottom: 0;
}

.draft-row strong {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-row span {
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.draft-actions {
  display: flex;
  gap: 6px;
}

.golden-list-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
}

.golden-list-head span {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.golden-list-head small {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.golden-list-head strong {
  color: var(--text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.golden-table-wrap {
  max-height: 430px;
  overflow-x: hidden;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
}

.golden-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}

.golden-table th {
  background: var(--bg-soft);
  color: var(--text-secondary);
  font-weight: 700;
  text-align: left;
  line-height: 1.2;
}

.resizable-th {
  position: relative;
}

.resize-handle {
  position: absolute;
  top: 0;
  right: -4px;
  bottom: 0;
  z-index: 2;
  width: 8px;
  cursor: col-resize;
  user-select: none;
}

.resize-handle:hover {
  background: rgba(37, 99, 235, 0.14);
}

.golden-table th,
.golden-table td {
  border-bottom: 1px solid var(--border-subtle);
  padding: 10px 10px;
  vertical-align: top;
}

.golden-table th {
  padding-top: 12px;
  padding-bottom: 12px;
}

.golden-table td {
  line-height: 1.45;
}

.golden-table tbody tr:last-child td {
  border-bottom: 0;
}

.golden-table tbody tr.disabled {
  opacity: 0.58;
}

.col-id {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-flavor {
  white-space: nowrap;
}

.col-set {
  text-align: center;
  white-space: nowrap;
}

.col-result {
  text-align: center;
  white-space: nowrap;
}

.col-strict {
  text-align: center;
  white-space: nowrap;
}

.col-rule {
  text-align: center;
  white-space: nowrap;
}

.col-count {
  text-align: center;
  white-space: nowrap;
}

.col-enabled,
.col-actions {
  text-align: center;
  white-space: nowrap;
}

.golden-table td.col-actions {
  display: flex;
  gap: 6px;
  justify-content: center;
}

.question-cell {
  color: var(--text-primary);
  line-height: 1.45;
  word-break: break-word;
}

.result-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  border-radius: 999px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
}

.col-result small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.col-result .result-failure-tag {
  color: #991b1b;
  font-weight: 600;
}

.col-result .result-cache-tag {
  color: #2563eb;
  font-weight: 600;
}

.smoke-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 2px 6px;
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
  font-weight: 700;
}

.muted-cell {
  color: var(--text-muted);
}

.result-queued {
  background: var(--bg-hover);
  color: var(--text-muted);
}

.result-running {
  background: #dbeafe;
  color: #1e40af;
}

.result-passed {
  background: #dcfce7;
  color: #166534;
}

.result-warning {
  background: #fef3c7;
  color: #92400e;
}

.result-failed {
  background: #fee2e2;
  color: #991b1b;
}

.enabled-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 700;
}

.enabled-on {
  background: #dcfce7;
  color: #166534;
}

.enabled-off {
  background: var(--bg-hover);
  color: var(--text-muted);
}

.draft-form {
  display: grid;
  gap: 12px;
}

.draft-form label {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.draft-form label > span {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.case-config-panel {
  display: grid;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: #fbfdff;
}

.config-line {
  display: grid;
  align-items: end;
  gap: 12px;
}

.config-line-strategy {
  grid-template-columns: minmax(0, 1fr);
}

.config-line-eval {
  grid-template-columns: minmax(220px, 340px) 96px;
}

.draft-form label.config-field {
  gap: 6px;
}

.config-field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.metadata-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.metadata-check input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--accent);
}

.min-citations-control,
.min-citations-input {
  width: 96px;
}

.segmented-control {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: #fff;
}

.segmented-control button {
  min-width: 0;
  height: 28px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.segmented-control button:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.segmented-control button.active {
  background: #fff;
  color: var(--accent);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.golden-empty {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 12px;
  padding: 12px;
}

.golden-empty.error {
  color: var(--error);
}

@media (max-width: 900px) {
  .option-grid-modes,
  .option-grid-scopes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .eval-top {
    align-items: flex-start;
    flex-direction: column;
  }

  .eval-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .option-grid-modes,
  .option-grid-scopes {
    grid-template-columns: minmax(0, 1fr);
  }

  .run-settings {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
