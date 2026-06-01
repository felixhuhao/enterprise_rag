<!-- Feedback records table — admin-only sub-component of EvaluateView. -->
<template>
  <div v-if="authStore.isAdmin" class="feedback-card">
    <div class="fb-header">
      <div class="fb-title">答案反馈</div>
      <a-button size="mini" @click="feedbackColumns.resetColumnWidths()">重置列宽</a-button>
    </div>
    <div class="draft-panel">
      <div class="draft-head">
        <span>基准测试集草稿</span>
        <span class="draft-count">{{ drafts.length }} 条</span>
      </div>
      <div v-if="draftPath" class="draft-path">{{ draftPath }}</div>
      <a-empty v-if="!drafts.length" description="暂无草稿" />
      <div v-else class="draft-list">
        <div v-for="draft in drafts.slice(0, 6)" :key="draft.id" class="draft-item">
          <span class="draft-question" :title="draft.question">{{ draft.question }}</span>
          <span class="draft-meta">{{ flavorLabel(draft.preferred_flavor) }}</span>
          <span v-if="draft.strict_evidence" class="draft-meta">仅资料</span>
          <span class="draft-source">#{{ draft.source_feedback_id }}</span>
        </div>
      </div>
    </div>
    <div :ref="setFeedbackTableContainer" class="feedback-table-wrap">
      <a-table
        :data="records"
        :pagination="{ pageSize: 20 }"
        row-key="id"
        size="small"
        column-resizable
        @column-resize="feedbackColumns.onColumnResize"
      >
        <template #columns>
          <a-table-column title="时间" data-index="created_at" :width="feedbackColumns.columnWidth('created_at')">
            <template #cell="{ record }">
              <span class="nowrap-cell">{{ formatTime(record.created_at) }}</span>
            </template>
          </a-table-column>
          <a-table-column title="用户" data-index="user_id" :width="feedbackColumns.columnWidth('user_id')" />
          <a-table-column title="评价" data-index="rating" :width="feedbackColumns.columnWidth('rating')">
            <template #cell="{ record }">
              <span class="rating-cell" :class="record.rating === 'up' ? 'rate-up' : 'rate-down'">
                {{ record.rating === 'up' ? '有帮助' : '无帮助' }}
              </span>
            </template>
          </a-table-column>
          <a-table-column title="问题" data-index="query" :width="feedbackColumns.columnWidth('query')" :ellipsis="true" />
          <a-table-column title="备注" data-index="comment" :width="feedbackColumns.columnWidth('comment')" :ellipsis="true" />
          <a-table-column title="答案" data-index="answer" :width="feedbackColumns.columnWidth('answer')">
            <template #cell="{ record }">
              <a-button size="mini" @click="openAnswer(record)">查看</a-button>
            </template>
          </a-table-column>
          <a-table-column title="基准测试集" data-index="golden" :width="feedbackColumns.columnWidth('golden')">
            <template #cell="{ record }">
              <a-button
                size="mini"
                :loading="promotingIds.has(record.id)"
                :disabled="record.in_golden_draft"
                @click="promoteToDraft(record)"
              >
                {{ record.in_golden_draft ? '已加入' : '加入草稿' }}
              </a-button>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </div>

    <a-modal v-model:visible="modalOpen" title="回答详情" :footer="false" :width="600">
      <div class="detail-answer">{{ modalAnswer }}</div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'
import {
  listFeedback,
  listGoldenDrafts,
  promoteFeedbackToGoldenDraft,
  type FeedbackRecord,
  type GoldenDraft,
} from '../../api/queryFeedback'
import { flavorLabel } from '../../utils/labelMaps'
import { useAutoFitColumns } from '../../composables/useAutoFitColumns'

const props = withDefaults(defineProps<{ filterUserId?: string }>(), { filterUserId: '' })

const authStore = useAuthStore()
const records = ref<FeedbackRecord[]>([])
const drafts = ref<GoldenDraft[]>([])
const draftPath = ref('')
const modalOpen = ref(false)
const modalAnswer = ref('')
const promotingIds = ref<Set<number>>(new Set())
const feedbackColumns = useAutoFitColumns('enterprise-rag:feedback-records:auto-v1', {
  created_at: { width: 180, minWidth: 146, maxWidth: 190 },
  user_id: { width: 95, minWidth: 78, maxWidth: 130 },
  rating: { width: 86, minWidth: 72, maxWidth: 100 },
  query: { width: 300, minWidth: 180, flex: true },
  comment: { width: 170, minWidth: 110, maxWidth: 240 },
  answer: { width: 60, minWidth: 56, maxWidth: 76 },
  golden: { width: 110, minWidth: 90, maxWidth: 130 },
}, { minWidth: 52 })

function setFeedbackTableContainer(element: Element | ComponentPublicInstance | null) {
  feedbackColumns.containerRef.value = element instanceof HTMLElement ? element : null
}

async function load() {
  if (!authStore.isAdmin) return
  await Promise.all([loadFeedback(), loadDrafts()])
}

async function loadFeedback() {
  try {
    records.value = await listFeedback(props.filterUserId)
  } catch {
    Message.error('反馈记录加载失败')
  }
}

async function loadDrafts() {
  try {
    const res = await listGoldenDrafts()
    drafts.value = res.drafts
    draftPath.value = res.path
  } catch {
    Message.error('基准测试集草稿加载失败')
  }
}

onMounted(load)
watch(() => props.filterUserId, load)

function formatTime(v: string) {
  if (!v) return '-'
  return v.replace('T', ' ').slice(0, 19)
}

function openAnswer(record: FeedbackRecord) {
  modalAnswer.value = record.answer || '(无回答)'
  modalOpen.value = true
}

async function promoteToDraft(record: FeedbackRecord) {
  if (record.in_golden_draft || promotingIds.value.has(record.id)) return
  promotingIds.value = new Set([...promotingIds.value, record.id])
  try {
    const res = await promoteFeedbackToGoldenDraft(record.id)
    record.in_golden_draft = true
    await loadDrafts()
    Message.success(res.status === 'exists' ? '已在基准测试集草稿中' : '已加入基准测试集草稿')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '加入基准测试集草稿失败')
  } finally {
    const next = new Set(promotingIds.value)
    next.delete(record.id)
    promotingIds.value = next
  }
}
</script>

<style scoped>
.feedback-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
  margin-top: 16px;
}
.fb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.fb-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}
.feedback-table-wrap {
  min-width: 0;
  overflow-x: hidden;
}
.draft-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fbfdff;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.draft-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}
.draft-count,
.draft-source {
  color: var(--text-muted);
  font-weight: 500;
}
.draft-path {
  margin-top: 3px;
  font-size: 11px;
  color: var(--text-muted);
  word-break: break-all;
}
.draft-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}
.draft-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.draft-question {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.draft-meta {
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-secondary);
  background: var(--bg-surface);
  white-space: nowrap;
}
.nowrap-cell,
.rating-cell {
  white-space: nowrap;
}
.rate-up { color: #166534; }
.rate-down { color: #991b1b; }
.detail-answer {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
}
</style>
