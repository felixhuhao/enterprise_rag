<template>
  <section class="jobs-panel">
    <header class="panel-head">
      <div>
        <div class="panel-title">后台任务</div>
        <p>最近的文档处理和评测任务。当前 {{ jobs.length }} 条。</p>
      </div>
      <a-button size="mini" :loading="loading" @click="$emit('refresh')">
        <template #icon><icon-refresh /></template>
        刷新
      </a-button>
    </header>

    <a-alert v-if="error" type="error" :content="error" />

    <a-empty v-else-if="!loading && !jobs.length" description="暂无任务记录" />

    <div
      v-else
      class="job-list"
    >
      <div class="job-list-head">
        <span>任务</span>
        <span>状态</span>
        <span>进度</span>
        <span>资源</span>
        <span>更新</span>
        <span></span>
      </div>
      <div v-for="job in jobs" :key="job.job_id" class="job-row">
        <div class="job-main">
          <strong>{{ jobTypeLabel(job.job_type) }}</strong>
          <span>{{ shortId(job.job_id) }}</span>
        </div>
        <div>
          <a-tag :color="statusColor(job.status)">{{ job.status_label || statusLabel(job.status) }}</a-tag>
        </div>
        <div class="progress-cell">
          <a-progress
            v-if="job.progress_percent !== null"
            :percent="job.progress_percent / 100"
            size="small"
            :show-text="false"
          />
          <span>{{ progressText(job) }}</span>
        </div>
        <div class="resource-cell">
          <span>{{ resourceLabel(job) }}</span>
          <small>{{ job.message || '-' }}</small>
        </div>
        <div class="time-cell">{{ formatTime(job.updated_at) }}</div>
        <div class="action-cell">
          <a-button size="mini" @click="openDetail(job)">详情</a-button>
        </div>
      </div>
    </div>

    <a-drawer
      v-model:visible="detailOpen"
      :width="560"
      title="任务详情"
      unmount-on-close
    >
      <div v-if="selectedJob" class="job-detail">
        <div class="detail-head">
          <a-tag :color="statusColor(selectedJob.status)">
            {{ selectedJob.status_label || statusLabel(selectedJob.status) }}
          </a-tag>
          <strong>{{ jobTypeLabel(selectedJob.job_type) }}</strong>
        </div>

        <div class="detail-grid">
          <span>任务 ID</span><strong>{{ selectedJob.job_id }}</strong>
          <span>资源</span><strong>{{ resourceLabel(selectedJob) }}</strong>
          <span>创建人</span><strong>{{ selectedJob.created_by || '-' }}</strong>
          <span>尝试次数</span><strong>{{ selectedJob.attempt_count || 1 }}</strong>
          <span>进度</span><strong>{{ progressText(selectedJob) }}</strong>
          <span>消息</span><strong>{{ selectedJob.message || '-' }}</strong>
          <span>创建时间</span><strong>{{ formatTime(selectedJob.created_at) }}</strong>
          <span>开始时间</span><strong>{{ formatTime(selectedJob.started_at) }}</strong>
          <span>结束时间</span><strong>{{ formatTime(selectedJob.finished_at) }}</strong>
          <span>更新时间</span><strong>{{ formatTime(selectedJob.updated_at) }}</strong>
        </div>

        <div v-if="selectedJob.error_code || selectedJob.error_detail" class="error-box">
          <strong>{{ selectedJob.error_code || 'ERROR' }}</strong>
          <p>{{ selectedJob.error_detail || '-' }}</p>
        </div>
      </div>
    </a-drawer>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconRefresh } from '@arco-design/web-vue/es/icon'
import type { JobRecord } from '../../api/adminJobs'

defineProps<{
  jobs: JobRecord[]
  loading: boolean
  error: string
}>()

defineEmits<{
  refresh: []
}>()

const detailOpen = ref(false)
const selectedJob = ref<JobRecord | null>(null)

function openDetail(job: JobRecord) {
  selectedJob.value = job
  detailOpen.value = true
}

function jobTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    document_ingestion: '文档处理',
    document_retry: '文档重试',
    golden_set_eval: '回归评测',
  }
  return labels[type] || type || '任务'
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
    canceled: '已取消',
  }
  return labels[status] || status || '未知'
}

function statusColor(status: string): string {
  if (status === 'succeeded') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'running') return 'blue'
  if (status === 'canceled') return 'gray'
  return 'orange'
}

function shortId(value: string): string {
  if (!value) return '-'
  return value.length > 16 ? `${value.slice(0, 10)}...${value.slice(-4)}` : value
}

function resourceLabel(job: JobRecord): string {
  const type = job.resource_type || 'resource'
  const id = job.resource_id || '-'
  if (type === 'document') return `文档 ${shortId(id)}`
  if (type === 'eval') return '基准测试集'
  return `${type} ${shortId(id)}`
}

function progressText(job: JobRecord): string {
  const total = Number(job.progress_total || 0)
  const current = Number(job.progress_current || 0)
  if (total > 0) return `${current} / ${total}`
  return job.status === 'queued' ? '等待启动' : '-'
}

function formatTime(value: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}
</script>

<style scoped>
.jobs-panel {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fbfdff;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

.panel-head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.job-list {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.job-list-head,
.job-row {
  display: grid;
  grid-template-columns: minmax(130px, 170px) 96px minmax(120px, 170px) minmax(180px, 1fr) 150px 72px;
  gap: 12px;
  align-items: center;
}

.job-list-head {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-hover);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}

.job-row {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}

.job-row:last-child {
  border-bottom: 0;
}

.job-main,
.resource-cell,
.progress-cell {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.job-main strong,
.resource-cell span {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-main span,
.resource-cell small,
.progress-cell span,
.time-cell {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-cell {
  text-align: right;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.detail-head strong {
  color: var(--text-primary);
  font-size: 16px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px 14px;
  align-items: start;
}

.detail-grid span {
  color: var(--text-muted);
  font-size: 12px;
}

.detail-grid strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.error-box {
  margin-top: 16px;
  padding: 12px;
  border: 1px solid #fecaca;
  border-radius: var(--radius-sm);
  background: #fef2f2;
}

.error-box strong {
  color: #991b1b;
  font-size: 12px;
}

.error-box p {
  margin: 6px 0 0;
  color: #7f1d1d;
  font-size: 12px;
  white-space: pre-wrap;
}

@media (max-width: 760px) {
  .panel-head {
    align-items: stretch;
    flex-direction: column;
  }

  .job-list-head {
    display: none;
  }

  .job-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .action-cell {
    text-align: left;
  }
}
</style>
