<!--
  反馈记录表 — Evaluate 页 admin-only 子组件。
-->
<template>
  <div v-if="authStore.isAdmin" class="feedback-card">
    <div class="fb-title">答案反馈</div>
    <a-table :data="records" :pagination="{ pageSize: 20 }" row-key="id" size="small">
      <template #columns>
        <a-table-column title="时间" :width="160">
          <template #cell="{ record }">{{ formatTime(record.created_at) }}</template>
        </a-table-column>
        <a-table-column title="用户" data-index="user_id" :width="80" />
        <a-table-column title="评价" :width="70">
          <template #cell="{ record }">
            <span :class="record.rating === 'up' ? 'rate-up' : 'rate-down'">
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
      </template>
    </a-table>

    <a-modal v-model:visible="modalOpen" title="回答详情" :footer="false" :width="600">
      <div class="detail-answer">{{ modalAnswer }}</div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { listFeedback, type FeedbackRecord } from '../../api/queryFeedback'

const authStore = useAuthStore()
const records = ref<FeedbackRecord[]>([])
const modalOpen = ref(false)
const modalAnswer = ref('')

onMounted(async () => {
  if (!authStore.isAdmin) return
  try {
    records.value = await listFeedback()
  } catch { /* empty */ }
})

function formatTime(v: string) {
  if (!v) return '—'
  return v.replace('T', ' ').slice(0, 19)
}

function openAnswer(record: FeedbackRecord) {
  modalAnswer.value = record.answer || '(无回答)'
  modalOpen.value = true
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
.rate-up { color: #166534; }
.rate-down { color: #991b1b; }
.detail-answer { white-space: pre-wrap; font-size: 13px; line-height: 1.6; max-height: 400px; overflow-y: auto; }
</style>
