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
  padding: 26px 28px;
  /* signature: faint engineering dot-grid over warm paper */
  background-color: var(--qc-paper, #f4f2ed);
  background-image: radial-gradient(circle at 1px 1px, var(--qc-grid, rgba(28, 26, 22, 0.045)) 1px, transparent 0);
  background-size: 22px 22px;
  background-position: -1px -1px;
}

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  gap: 12px;
  text-align: center;
  animation: fadeInUp 0.4s var(--ease-out) both;
}
.hint-icon {
  position: relative;
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: var(--qc-surface);
  border: 1px solid var(--qc-cobalt-edge);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--qc-cobalt);
  box-shadow: 0 0 0 6px var(--qc-cobalt-soft), var(--shadow-md);
}
.hint-title {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}
.empty-hint p {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}
.sample-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  max-width: 680px;
  margin-top: 10px;
}
.sample-list button {
  padding: 7px 13px 7px 11px;
  border: 1px solid var(--qc-line-2);
  border-radius: 999px;
  background: var(--qc-surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.16s, border-color 0.16s, background 0.16s, transform 0.16s;
}
.sample-list button::before {
  content: "›";
  margin-right: 6px;
  font-family: var(--font-mono);
  color: var(--qc-cobalt);
  font-weight: 600;
}
.sample-list button:hover {
  color: var(--qc-cobalt-hover);
  border-color: var(--qc-cobalt-edge);
  background: var(--qc-cobalt-soft);
  transform: translateY(-1px);
}

/* 消息气泡 */
.message-bubble {
  display: flex;
  gap: 14px;
  margin-bottom: 22px;
  animation: fadeInUp 0.26s var(--ease-out) both;
}
.message-bubble.user {
  flex-direction: row-reverse;
}

.avatar-user,
.avatar-ai {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.avatar-user {
  background: var(--qc-cobalt-soft);
  border: 1px solid var(--qc-cobalt-edge);
  color: var(--qc-cobalt-hover);
}
.avatar-ai {
  background: var(--qc-cobalt);
  border: 1px solid var(--qc-cobalt);
  color: #fff;
  box-shadow: 0 0 0 4px var(--qc-cobalt-soft);
}

.bubble-body {
  max-width: min(860px, 82%);
}
.role-label {
  font-family: var(--font-body);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.user .role-label {
  text-align: right;
  color: var(--qc-cobalt-hover);
}

.content {
  padding: 13px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.72;
  word-break: break-word;
}
.message-bubble.user .content {
  background: var(--qc-cobalt-soft);
  border: 1px solid var(--qc-cobalt-edge);
  border-top-right-radius: 4px;
  color: var(--text-primary);
}
.message-bubble.assistant .content {
  position: relative;
  background: var(--qc-surface);
  border: 1px solid var(--qc-line);
  border-top-left-radius: 4px;
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}
/* answer marker: thin cobalt edge */
.message-bubble.assistant .content::before {
  content: "";
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 2px;
  border-radius: 2px;
  background: linear-gradient(var(--qc-cobalt), var(--qc-cobalt-edge));
  opacity: 0.6;
}

/* Markdown 样式 — refined "document" typography */
.content :deep(p) { margin: 0 0 10px; }
.content :deep(p:last-child) { margin-bottom: 0; }
.content :deep(pre) {
  background: #181a24;
  border: 1px solid #2a2d3a;
  color: #d6dcec;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.6;
  margin: 10px 0;
}
.content :deep(code) { font-family: var(--font-mono); font-size: 12.5px; }
.content :deep(:not(pre) > code) {
  background: var(--qc-cobalt-soft);
  border: 1px solid var(--qc-cobalt-edge);
  color: var(--qc-cobalt-hover);
  padding: 1px 6px;
  border-radius: 5px;
  font-size: 12px;
}
.content :deep(a) {
  color: var(--qc-cobalt-hover);
  text-decoration: none;
  border-bottom: 1px solid var(--qc-cobalt-edge);
  transition: border-color 0.15s;
}
.content :deep(a:hover) { border-bottom-color: var(--qc-cobalt); }
.content :deep(blockquote) {
  border-left: 3px solid var(--qc-cobalt-edge);
  margin: 10px 0;
  padding: 4px 14px;
  color: var(--text-secondary);
  background: var(--qc-cobalt-soft);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.content :deep(h1), .content :deep(h2), .content :deep(h3) {
  font-family: var(--font-display);
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.3;
  margin: 18px 0 8px;
  color: var(--text-primary);
}
.content :deep(h1) { font-size: 18px; }
.content :deep(h2) { font-size: 16px; }
.content :deep(h3) { font-size: 14.5px; }
.content :deep(h1:first-child),
.content :deep(h2:first-child),
.content :deep(h3:first-child) { margin-top: 0; }
.content :deep(ul), .content :deep(ol) { padding-left: 20px; margin: 8px 0; }
.content :deep(li) { margin: 4px 0; }
.content :deep(strong) { font-weight: 600; color: var(--qc-ink); }
.content :deep(hr) {
  border: none;
  border-top: 1px solid var(--qc-line);
  margin: 14px 0;
}
.content :deep(table) {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  margin: 12px 0;
  font-variant-numeric: tabular-nums;
  border: 1px solid var(--qc-line);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.content :deep(th), .content :deep(td) {
  border-bottom: 1px solid var(--qc-line);
  border-right: 1px solid var(--qc-line);
  padding: 7px 11px;
  font-size: 13px;
  text-align: left;
}
.content :deep(th:last-child), .content :deep(td:last-child) { border-right: none; }
.content :deep(tr:last-child td) { border-bottom: none; }
.content :deep(th) {
  background: var(--qc-paper);
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--text-secondary);
}
.content :deep(tbody tr:nth-child(even) td) { background: rgba(28, 26, 22, 0.018); }

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
