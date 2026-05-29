<!-- Feedback records table — admin-only sub-component of FeedbackView. -->
<template>
  <div v-if="authStore.isAdmin" class="feedback-card">
    <div class="fb-title">答案反馈</div>
    <a-table :data="records" :pagination="{ pageSize: 20 }" row-key="id" size="small">
      <template #columns>
        <a-table-column title="时间" :width="190">
          <template #cell="{ record }">
            <span class="nowrap-cell">{{ formatTime(record.created_at) }}</span>
          </template>
        </a-table-column>
        <a-table-column title="用户" data-index="user_id" :width="80" />
        <a-table-column title="评价" :width="96">
          <template #cell="{ record }">
            <span class="rating-cell" :class="record.rating === 'up' ? 'rate-up' : 'rate-down'">
              {{ record.rating === 'up' ? '有帮助' : '无帮助' }}
            </span>
          </template>
        </a-table-column>
        <a-table-column title="问题" data-index="query" :ellipsis="true" />
        <a-table-column title="备注" data-index="comment" :width="150" :ellipsis="true" />
        <a-table-column title="答案" :width="60">
          <template #cell="{ record }">
            <a-button size="mini" @click="openAnswer(record)">查看</a-button>
          </template>
        </a-table-column>
        <a-table-column title="Golden Set" :width="110">
          <template #cell="{ record }">
            <a-button
              size="mini"
              :loading="promotingIds.has(record.id)"
              @click="promoteToDraft(record)"
            >
              加入草稿
            </a-button>
          </template>
        </a-table-column>
      </template>
    </a-table>

    <a-modal v-model:visible="modalOpen" title="回答详情" :footer="false" :width="600">
      <div class="detail-answer">{{ modalAnswer }}</div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'
import {
  listFeedback,
  promoteFeedbackToGoldenDraft,
  type FeedbackRecord,
} from '../../api/queryFeedback'

const props = withDefaults(defineProps<{ filterUserId?: string }>(), { filterUserId: '' })

const authStore = useAuthStore()
const records = ref<FeedbackRecord[]>([])
const modalOpen = ref(false)
const modalAnswer = ref('')
const promotingIds = ref<Set<number>>(new Set())

async function load() {
  if (!authStore.isAdmin) return
  try {
    records.value = await listFeedback(props.filterUserId)
  } catch {
    // Feedback is auxiliary; keep the page usable if loading fails.
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
  if (promotingIds.value.has(record.id)) return
  promotingIds.value = new Set([...promotingIds.value, record.id])
  try {
    const res = await promoteFeedbackToGoldenDraft(record.id)
    Message.success(res.status === 'exists' ? '已在 Golden Set 草稿中' : '已加入 Golden Set 草稿')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '加入 Golden Set 草稿失败')
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
.fb-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 12px;
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
