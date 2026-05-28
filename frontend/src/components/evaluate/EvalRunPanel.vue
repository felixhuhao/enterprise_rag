<!--
  Golden Set 回归运行面板 — admin-only。
-->
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
        <span class="sum-item">均分 {{ (summary.overall.avg_score * 100).toFixed(1) }}%</span>
        <span class="sum-item">通过率 {{ (summary.overall.pass_rate * 100).toFixed(1) }}%</span>
      </div>
    </div>

    <div v-if="status === 'failed' && error" class="eval-error">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { getEvalStatus, runEval, type EvalSummary } from '../../api/adminEval'

const authStore = useAuthStore()
const status = ref('idle')
const summary = ref<EvalSummary | null>(null)
const error = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABELS: Record<string, string> = {
  idle: '空闲', running: '运行中', succeeded: '已完成', failed: '失败',
}
const statusLabel = ref(STATUS_LABELS.idle)
const buttonLabels: Record<string, string> = {
  idle: '运行 Golden Set', running: '评估运行中', succeeded: '重新运行', failed: '重试评估',
}
const buttonLabel = ref(buttonLabels.idle)

async function refresh() {
  try {
    const s = await getEvalStatus()
    status.value = s.status
    statusLabel.value = STATUS_LABELS[s.status] ?? s.status
    buttonLabel.value = buttonLabels[s.status] ?? '运行'
    summary.value = s.summary
    error.value = s.error
  } catch { /* ignore */ }
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
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
}
.status-idle { color: var(--text-muted); background: var(--bg-hover); }
.status-running { color: #1e40af; background: #dbeafe; }
.status-succeeded { color: #166534; background: #dcfce7; }
.status-failed { color: #991b1b; background: #fee2e2; }

.eval-summary { margin-top: 8px; }
.sum-row { display: flex; gap: 12px; }
.sum-item { font-size: 12px; color: var(--text-secondary); font-weight: 600; font-variant-numeric: tabular-nums; }

.eval-error { margin-top: 6px; font-size: 12px; color: var(--error); }
</style>
