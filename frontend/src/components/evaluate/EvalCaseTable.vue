<template>
  <section class="eval-case-table">
    <div class="case-table-head">
      <div>
        <span>问题诊断</span>
        <small>{{ issueCases.length }} 条需要查看</small>
      </div>
      <div v-if="issueCases.length" class="case-table-filters">
        <a-select v-model="categoryFilter" size="small" class="case-filter-select">
          <a-option value="">全部原因</a-option>
          <a-option v-for="item in categoryOptions" :key="item.key" :value="item.key">
            {{ item.label }}
          </a-option>
        </a-select>
        <a-select v-model="flavorFilter" size="small" class="case-filter-select">
          <a-option value="">全部策略</a-option>
          <a-option v-for="item in flavorOptions" :key="item.key" :value="item.key">
            {{ item.label }}
          </a-option>
        </a-select>
      </div>
    </div>

    <div v-if="!issueCases.length" class="case-table-empty">暂无失败或警告用例</div>
    <div v-else-if="!filteredCases.length" class="case-table-empty">当前筛选没有匹配用例</div>
    <div v-else class="case-table-wrap">
      <table>
        <thead>
          <tr>
            <th class="col-id">ID</th>
            <th class="col-status">状态</th>
            <th class="col-question">问题</th>
            <th class="col-flavor">策略</th>
            <th class="col-reason">原因</th>
            <th class="col-score">得分</th>
            <th class="col-cache">Judge</th>
            <th class="col-action">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in filteredCases" :key="item.id">
            <td class="col-id" :title="item.id">{{ item.id }}</td>
            <td class="col-status">
              <span class="status-pill" :class="'status-' + item.status">
                {{ item.label || evalResultStatusLabel(item.status) }}
              </span>
            </td>
            <td class="col-question">
              <strong :title="item.question">{{ item.question || '-' }}</strong>
              <small>
                {{ evalModeLabel(item.eval_mode || '') }} / {{ evalTypeLabel(item.eval_type || '') }}
                <template v-if="item.strict_evidence"> / 仅资料</template>
              </small>
            </td>
            <td class="col-flavor">{{ caseFlavorLabel(item) }}</td>
            <td class="col-reason">
              <div v-if="caseCategories(item).length" class="reason-list">
                <span
                  v-for="category in caseCategories(item)"
                  :key="category"
                  class="reason-pill"
                >
                  {{ failureCategoryLabel(category) }}
                </span>
              </div>
              <span v-if="!caseCategories(item).length" class="reason-empty">-</span>
            </td>
            <td class="col-score">{{ formatEvalScore(item.score) || '-' }}</td>
            <td class="col-cache">
              <span v-if="item.judge_cache_status" :title="judgeCacheLabel(item.judge_cache_status)">
                {{ judgeCacheShortLabel(item.judge_cache_status) }}
              </span>
              <span v-else>-</span>
            </td>
            <td class="col-action">
              <a-button size="mini" :disabled="!item.id" @click="emit('open', item)">
                详情
              </a-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EvalCaseResult } from '../../api/adminEval'
import {
  evalModeLabel,
  evalResultStatusLabel,
  evalTypeLabel,
  failureCategoryLabel,
  formatEvalScore,
  judgeCacheLabel,
} from '../../utils/evalLabels'
import { flavorLabel } from '../../utils/labelMaps'

const props = defineProps<{
  cases: EvalCaseResult[]
}>()

const emit = defineEmits<{
  open: [item: EvalCaseResult]
}>()

const categoryFilter = ref('')
const flavorFilter = ref('')

const issueCases = computed(() => {
  return props.cases.filter((item) => item.status === 'failed' || item.status === 'warning')
})

const categoryOptions = computed(() => {
  const keys = new Set<string>()
  for (const item of issueCases.value) {
    for (const category of caseCategories(item)) keys.add(category)
  }
  return [...keys].sort().map((key) => ({ key, label: failureCategoryLabel(key) }))
})

const flavorOptions = computed(() => {
  const keys = new Set<string>()
  for (const item of issueCases.value) {
    const key = caseFlavor(item)
    if (key) keys.add(key)
  }
  return [...keys].sort().map((key) => ({ key, label: flavorLabel(key) }))
})

const filteredCases = computed(() => {
  return issueCases.value.filter((item) => {
    if (categoryFilter.value && !caseCategories(item).includes(categoryFilter.value)) return false
    if (flavorFilter.value && caseFlavor(item) !== flavorFilter.value) return false
    return true
  })
})

function caseCategories(item: EvalCaseResult): string[] {
  if (Array.isArray(item.failure_categories) && item.failure_categories.length) {
    return item.failure_categories.filter(Boolean)
  }
  return item.failure_category ? [item.failure_category] : []
}

function caseFlavor(item: EvalCaseResult): string {
  return item.actual_retrieval_flavor || item.preferred_flavor || ''
}

function caseFlavorLabel(item: EvalCaseResult): string {
  const value = caseFlavor(item)
  return value ? flavorLabel(value) : '-'
}

function judgeCacheShortLabel(value: string): string {
  if (value === 'cached') return '命中'
  if (value === 'fresh') return '新评'
  if (value === 'miss') return '未中'
  if (value === 'error') return '错误'
  return value || '-'
}
</script>

<style scoped>
.eval-case-table {
  margin-top: 14px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.case-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.case-table-head > div:first-child {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.case-table-head span {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
}

.case-table-head small {
  color: var(--text-muted);
  font-size: 11px;
}

.case-table-filters {
  display: grid;
  grid-template-columns: repeat(2, 140px);
  gap: 8px;
  justify-content: flex-end;
}

.case-filter-select {
  width: 140px;
}

.case-table-empty {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 12px;
  padding: 12px;
}

.case-table-wrap {
  max-height: 300px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
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
  padding: 9px 10px;
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

.col-id {
  width: 128px;
  overflow: hidden;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-status,
.col-score,
.col-cache,
.col-action {
  width: 74px;
  text-align: center;
  white-space: nowrap;
}

.col-flavor {
  width: 82px;
  white-space: nowrap;
}

.col-reason {
  width: 190px;
}

.col-question {
  min-width: 0;
}

.col-question strong {
  display: block;
  overflow: hidden;
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-question small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
}

.status-pill,
.reason-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
}

.status-failed {
  background: #fee2e2;
  color: #991b1b;
}

.status-warning {
  background: #fef3c7;
  color: #92400e;
}

.reason-pill {
  background: #fbfdff;
  border: 1px solid var(--border);
  color: var(--text-secondary);
}

.reason-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.reason-empty {
  color: var(--text-muted);
}

@media (max-width: 760px) {
  .case-table-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .case-table-filters {
    grid-template-columns: minmax(0, 1fr);
    justify-content: flex-start;
    width: 100%;
  }

  .case-filter-select {
    width: 100%;
  }
}
</style>
