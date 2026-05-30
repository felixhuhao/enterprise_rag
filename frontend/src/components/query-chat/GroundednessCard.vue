<!--
  资料支持度卡片 — 答案依据覆盖检查结果。
  收起态显示分数摘要，展开态列 claims。
  低分或 warning 时默认展开。
-->
<template>
  <div v-if="result && result.status !== 'skipped'" class="groundedness-card">
    <div class="gr-header" @click="expanded = !expanded">
      <icon-check-circle />
      <span class="gr-summary">{{ summaryText }}</span>
      <icon-down :class="{ rotated: expanded }" />
    </div>
    <div v-if="expanded" class="gr-body">
      <div v-if="result.warning" class="gr-warning">{{ result.warning }}</div>
      <div v-for="(c, i) in result.claims" :key="i" class="gr-claim">
        <div class="gr-claim-header">
          <span :class="['gr-verdict', `verdict-${c.verdict}`]">{{ verdictLabel(c.verdict) }}</span>
          <span v-if="c.claim_type !== 'factual'" class="gr-type">{{ claimTypeLabel(c.claim_type) }}</span>
          <span class="gr-claim-text">{{ c.claim }}</span>
        </div>
        <div v-if="c.evidence" class="gr-evidence">「{{ c.evidence }}」</div>
        <div v-if="c.citation_ids.length" class="gr-citations">
          <span v-for="cid in c.citation_ids" :key="cid" class="gr-cid">{{ cid }}</span>
        </div>
      </div>
      <div v-if="!result.claims.length" class="gr-empty">
        {{ result.status === 'unavailable' ? '检查失败，暂无详情' : '未提取到可检查的事实主张' }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { IconCheckCircle, IconDown } from '@arco-design/web-vue/es/icon'
import type { GroundednessResult } from '../../stores/queryChat'

const props = defineProps<{ result: GroundednessResult | null | undefined }>()

const WARNING_THRESHOLD = 0.7

const expanded = ref(shouldAutoExpand(props.result))

function shouldAutoExpand(result: GroundednessResult | null | undefined): boolean {
  return result != null && (
    (result.groundedness_score != null && result.groundedness_score < WARNING_THRESHOLD)
    || result.warning != null
  )
}

watch(
  () => props.result,
  (result) => {
    if (shouldAutoExpand(result)) expanded.value = true
  },
  { deep: true },
)

const summaryText = computed(() => {
  if (!props.result) return ''
  if (props.result.status === 'skipped') return '资料支持度检查已跳过'
  if (props.result.status === 'unavailable') return '资料支持度检查失败'
  const score = props.result.groundedness_score
  if (score == null) return '资料支持度：不适用'
  const pct = Math.round(score * 100)
  const total = props.result.claims.length
  return `资料支持度：${pct}%  ${total} 条主张`
})

const VERDICT_LABELS: Record<string, string> = {
  supported: '已支撑',
  partially_supported: '部分支撑',
  unsupported: '未支撑',
  contradicted: '矛盾',
}

function verdictLabel(v: string): string {
  return VERDICT_LABELS[v] ?? v
}

function claimTypeLabel(type?: string): string {
  return type === 'no_answer' ? '无答案声明' : '事实主张'
}
</script>

<style scoped>
.groundedness-card {
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-surface);
}

.gr-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: #f0fdf4;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  transition: color 0.2s;
}
.gr-header:hover {
  color: var(--text-primary);
}
.gr-header .rotated {
  transform: rotate(180deg);
}

.gr-summary {
  flex: 1;
  font-family: var(--font-display);
  font-weight: 700;
}

.gr-body {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--border);
}

.gr-warning {
  padding: 8px 10px;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: #92400e;
  margin-bottom: 8px;
}

.gr-claim {
  padding: 6px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.gr-claim:last-child {
  border-bottom: none;
}

.gr-claim-header {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.gr-verdict {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 999px;
  line-height: 18px;
}
.verdict-supported {
  background: #dcfce7;
  color: #166534;
}
.verdict-partially_supported {
  background: #fef3c7;
  color: #92400e;
}
.verdict-unsupported {
  background: #fee2e2;
  color: #991b1b;
}
.verdict-contradicted {
  background: #fecaca;
  color: #7f1d1d;
}

.gr-type {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 999px;
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #86efac;
}

.gr-claim-text {
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.5;
}

.gr-evidence {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-muted);
  padding-left: 4px;
  border-left: 2px solid var(--border);
  font-style: italic;
}

.gr-citations {
  margin-top: 3px;
  display: flex;
  gap: 4px;
}

.gr-cid {
  font-size: 10px;
  font-weight: 600;
  color: var(--accent);
  padding: 0 4px;
  border-radius: 999px;
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
}

.gr-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 4px 0;
}
</style>
