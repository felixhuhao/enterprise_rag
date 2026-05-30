<!--
  查询消息列表 — 自动滚动，每条 assistant 消息绑定自己的 retrievalInfo
-->
<template>
  <div ref="listRef" class="message-list">
    <div v-if="messages.length === 0" class="empty-hint">
      <div class="hint-icon">?</div>
      <div class="hint-title">从知识库提问</div>
      <p>答案会附带检索链路、引用来源和耗时 trace。</p>
      <div class="sample-list">
        <button
          v-for="sample in sampleQuestions"
          :key="sample"
          type="button"
          @click="store.sendMessage(sample)"
        >
          {{ sample }}
        </button>
      </div>
    </div>
    <template v-for="(msg, i) in messages" :key="msg.id">
      <!-- user 消息直接渲染 -->
      <div v-if="msg.role === 'user'" :class="['message-bubble', 'user']">
        <div class="avatar"><div class="avatar-user">U</div></div>
        <div class="bubble-body">
          <div class="role-label">问题</div>
          <div class="content">{{ msg.content }}</div>
        </div>
      </div>
      <!-- assistant 消息: Markdown 渲染 + 引用 -->
      <div v-else :class="['message-bubble', 'assistant']">
        <div class="avatar">
          <div class="avatar-ai">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 1L14.9282 5V13L8 17L1.07179 13V5L8 1Z" fill="currentColor" opacity="0.3"/>
              <path d="M8 4L12.3301 6.5V11.5L8 14L3.66987 11.5V6.5L8 4Z" fill="currentColor"/>
            </svg>
          </div>
        </div>
        <div class="bubble-body">
          <div class="role-label">回答</div>
          <!-- 检索链路面板 -->
          <RetrievalInfo
            v-if="msg.retrievalInfo"
            :info="msg.retrievalInfo"
            :rerank-items="msg.rerankItems"
            :trace="msg.trace"
          />
          <div class="content" v-html="renderMarkdown(msg.content)"></div>
          <!-- 引用卡片 -->
          <CitationCard v-if="msg.citations?.length" :citations="msg.citations" />
          <!-- 依据覆盖检查 -->
          <GroundednessCard v-if="msg.groundedness" :result="msg.groundedness" />
          <!-- 反馈按钮 -->
          <FeedbackButtons
            v-if="msg.role === 'assistant' && msg.content && !store.isStreaming"
            :payload="feedbackPayload(msg, i)"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { QueryChatMessage } from '../../stores/queryChat'
import { useQueryChatStore } from '../../stores/queryChat'
import type { FeedbackPayload } from '../../api/queryFeedback'
import RetrievalInfo from './RetrievalInfo.vue'
import CitationCard from './CitationCard.vue'
import GroundednessCard from './GroundednessCard.vue'
import FeedbackButtons from './FeedbackButtons.vue'

const store = useQueryChatStore()

const props = defineProps<{
  messages: QueryChatMessage[]
}>()

const listRef = ref<HTMLElement | null>(null)
const sampleQuestions = [
  '差旅报销需要哪些审批材料？',
  '员工需要遵守哪些信息安全要求？',
  '哪些公司提到了年度培训计划？',
]

/** Markdown 渲染 */
function renderMarkdown(content: string) {
  if (!content) return '<span class="typing-hint">思考中...</span>'
  return DOMPurify.sanitize(marked.parse(content) as string)
}

/** 构造反馈 payload */
function feedbackPayload(msg: QueryChatMessage, index: number): FeedbackPayload {
  const userMsg = index > 0 ? props.messages[index - 1] : null
  return {
    session_id: store.sessionId,
    message_id: msg.id,
    query: userMsg?.role === 'user' ? userMsg.content : '',
    answer: msg.content,
    citations: msg.citations ?? [],
    retrieved_chunks: [],  // TODO: push retrieved chunks from SSE into chat store
    retrieval_flavor: msg.retrievalInfo?.retrieval_flavor ?? 'balanced',
    strict_evidence: msg.retrievalInfo?.strict_evidence ?? false,
    rating: '',
    comment: '',
  }
}

/** 自动滚动到底部 */
function scrollToBottom() {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}

watch(() => props.messages, scrollToBottom, { deep: true })
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 22px 24px;
  background: #fbfcfe;
}

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  gap: 10px;
  text-align: center;
}
.hint-icon {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-lg);
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: var(--accent);
}
.hint-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}
.empty-hint p {
  margin: 0;
  font-size: 13px;
}
.sample-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  max-width: 680px;
  margin-top: 8px;
}
.sample-list button {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}
.sample-list button:hover {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--accent-subtle);
}

/* 消息气泡 */
.message-bubble {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  animation: fadeInUp 0.22s var(--ease-out) both;
}
.message-bubble.user {
  flex-direction: row-reverse;
}

.avatar-user,
.avatar-ai {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.avatar-user {
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  color: #4338ca;
}
.avatar-ai {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--info);
}

.bubble-body {
  max-width: min(860px, 82%);
}
.role-label {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.user .role-label {
  text-align: right;
}

.content {
  padding: 12px 14px;
  border-radius: var(--radius-lg);
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.message-bubble.user .content {
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  color: var(--text-primary);
}
.message-bubble.assistant .content {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}

/* Markdown 样式 */
.content :deep(pre) {
  background: #0f172a;
  border: 1px solid var(--border);
  color: #C8D0E0;
  padding: 14px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
}
.content :deep(code) { font-size: 13px; }
.content :deep(:not(pre) > code) {
  background: var(--bg-hover);
  border: 1px solid var(--border);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.content :deep(a) {
  color: var(--info);
  text-decoration: none;
  border-bottom: 1px solid rgba(91, 156, 246, 0.3);
}
.content :deep(blockquote) {
  border-left: 3px solid var(--accent-dim);
  margin: 8px 0;
  padding: 4px 12px;
  color: var(--text-secondary);
}
.content :deep(h1), .content :deep(h2), .content :deep(h3) {
  font-family: var(--font-display);
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--text-primary);
}
.content :deep(ul), .content :deep(ol) { padding-left: 20px; }
.content :deep(li) { margin: 4px 0; }
.content :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; }
.content :deep(th), .content :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 10px;
  font-size: 13px;
}
.content :deep(th) { background: var(--bg-hover); font-weight: 600; }

.typing-hint {
  color: var(--text-muted);
  font-style: italic;
  animation: fadeIn 0.5s ease-in-out infinite alternate;
}

@media (max-width: 840px) {
  .message-list {
    padding: 16px;
  }

  .bubble-body {
    max-width: calc(100% - 44px);
  }

  .sample-list {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
