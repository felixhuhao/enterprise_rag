<!--
  反馈按钮 — 拇指向上/向下，已提交后禁用。
-->
<template>
  <div class="feedback-row">
    <span class="feedback-label">这个回答有帮助吗？</span>
    <button
      class="fb-btn"
      :class="{ active: submitted && rating === 'up' }"
      :disabled="submitted"
      @click="onRate('up')"
      title="有帮助"
    >
      <icon-thumb-up />
    </button>
    <button
      class="fb-btn"
      :class="{ active: submitted && rating === 'down' }"
      :disabled="submitted"
      @click="onRate('down')"
      title="没帮助"
    >
      <icon-thumb-down />
    </button>
    <span v-if="submitted" class="fb-done">{{ rating === 'up' ? '感谢反馈' : '感谢反馈' }}</span>
  </div>
  <!-- downvote comment -->
  <div v-if="showComment" class="fb-comment">
    <a-input
      v-model="comment"
      placeholder="哪里不对？（可选）"
      size="small"
      :max-length="500"
      @keydown.enter="submitFeedback"
    />
    <a-button size="mini" @click="submitFeedback">提交</a-button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconThumbUp, IconThumbDown } from '@arco-design/web-vue/es/icon'
import { submitFeedback as submitApi, type FeedbackPayload } from '../../api/queryFeedback'

const props = defineProps<{ payload: FeedbackPayload }>()

const submitted = ref(false)
const rating = ref('')
const showComment = ref(false)
const comment = ref('')

async function onRate(r: 'up' | 'down') {
  rating.value = r
  if (r === 'up') {
    await submitFeedback()
  } else {
    showComment.value = true
  }
}

async function submitFeedback() {
  await submitApi({ ...props.payload, rating: rating.value, comment: comment.value })
  submitted.value = true
}
</script>

<style scoped>
.feedback-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.feedback-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-right: 4px;
}
.fb-btn {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-muted);
  border-radius: 4px;
  padding: 2px 6px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
}
.fb-btn:not(:disabled):hover { color: var(--accent); border-color: var(--border-accent); }
.fb-btn.active { color: var(--accent); border-color: var(--border-accent); background: var(--accent-subtle); }
.fb-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fb-done { font-size: 12px; color: var(--text-muted); }
.fb-comment { display: flex; gap: 6px; margin-top: 6px; }
.fb-comment :deep(.arco-input) { flex: 1; }
</style>
