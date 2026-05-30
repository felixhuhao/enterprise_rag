<template>
  <div v-if="authStore.isAdmin" class="eval-panel">
    <div class="eval-header">
      <span class="eval-title">Golden Set 回归</span>
      <span class="eval-status" :class="'status-' + status">{{ statusLabel }}</span>
    </div>

    <div class="eval-actions">
      <a-button
        :type="status === 'running' ? 'secondary' : 'primary'"
        :loading="status === 'running'"
        :disabled="status === 'running'"
        size="small"
        @click="onRun"
      >
        {{ buttonLabel }}
      </a-button>
    </div>

    <div v-if="status === 'succeeded' && summary" class="eval-summary">
      <div class="sum-row">
        <span class="sum-item">{{ summary.overall.count }} 题</span>
        <span class="sum-item">均分 {{ percent(summary.overall.avg_score) }}</span>
        <span class="sum-item">通过率 {{ percent(summary.overall.pass_rate) }}</span>
      </div>

      <div v-if="flavorRows.length" class="flavor-breakdown">
        <div class="breakdown-title">按 Flavor</div>
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
        Strict：{{ summary.per_strict.count }} 题，
        均分 {{ percent(summary.per_strict.avg_score) }}，
        通过 {{ percent(summary.per_strict.pass_rate) }}
      </div>
    </div>

    <div v-if="status === 'failed' && error" class="eval-error">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { getEvalStatus, runEval, type EvalSummary } from '../../api/adminEval'

const authStore = useAuthStore()
const status = ref('idle')
const summary = ref<EvalSummary | null>(null)
const error = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
}

const BUTTON_LABELS: Record<string, string> = {
  idle: '运行 Golden Set',
  running: '评估运行中',
  succeeded: '重新运行',
  failed: '重试评估',
}

const flavorLabels: Record<string, string> = {
  balanced: '标准问答',
  exact: '精确查找',
  recall: '全面查找',
  discovery: '关联查找',
}

const statusLabel = computed(() => STATUS_LABELS[status.value] ?? status.value)
const buttonLabel = computed(() => BUTTON_LABELS[status.value] ?? '运行')

const flavorRows = computed(() => {
  const data = summary.value?.per_flavor
  if (!data) return []
  return (['balanced', 'exact', 'recall', 'discovery'] as const)
    .filter((key) => data[key])
    .map((key) => ({ key, label: flavorLabels[key], metric: data[key] }))
})

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(1)}%`
}

async function refresh() {
  try {
    const s = await getEvalStatus()
    status.value = s.status
    summary.value = s.summary
    error.value = s.error
  } catch {
    // keep existing UI state
  }
}

async function onRun() {
  status.value = 'running'
  await runEval(false)
  await refresh()
}

onMounted(() => {
  refresh()
  timer = setInterval(() => {
    if (status.value === 'running') refresh()
  }, 2000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.eval-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px 18px;
  margin-top: 16px;
}

.eval-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
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
  gap: 12px;
}

.sum-item {
  font-size: 12px;
  color: var(--text-secondary);
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
</style>
