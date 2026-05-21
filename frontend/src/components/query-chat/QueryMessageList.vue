<!--
  查询消息列表 — 自动滚动，复用 MessageBubble 渲染
-->
<template>
  <div ref="listRef" class="message-list">
    <div v-if="messages.length === 0" class="empty-hint">
      <div class="hint-icon">?</div>
      <p>输入问题查询知识库</p>
    </div>
    <template v-for="msg in messages" :key="msg.id">
      <!-- user 消息直接渲染 -->
      <div v-if="msg.role === 'user'" :class="['message-bubble', 'user']">
        <div class="avatar"><div class="avatar-user">U</div></div>
        <div class="bubble-body">
          <div class="role-label">你</div>
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
          <div class="role-label">AI 助手</div>
          <!-- 检索步骤信息 -->
          <RetrievalInfo v-if="retrievalInfo && isLastAssistant(msg.id)" :info="retrievalInfo" :rerank-items="rerankItems" />
          <div class="content" v-html="renderMarkdown(msg.content)"></div>
          <!-- 引用卡片 -->
          <CitationCard v-if="msg.citations?.length" :citations="msg.citations" />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { QueryChatMessage, RetrievalInfo as RetrievalInfoType, RerankItem } from '../../stores/queryChat'
import RetrievalInfo from './RetrievalInfo.vue'
import CitationCard from './CitationCard.vue'

const props = defineProps<{
  messages: QueryChatMessage[]
  retrievalInfo: RetrievalInfoType | null
  rerankItems?: RerankItem[]
}>()

const listRef = ref<HTMLElement | null>(null)

/** 判断是否是最后一条 assistant 消息（用于显示 retrieval info） */
function isLastAssistant(id: string) {
  const lastAssistant = [...props.messages].reverse().find((m) => m.role === 'assistant')
  return lastAssistant?.id === id
}

/** Markdown 渲染 */
function renderMarkdown(content: string) {
  if (!content) return '<span class="typing-hint">思考中...</span>'
  return DOMPurify.sanitize(marked.parse(content) as string)
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
  padding: 20px;
}

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  gap: 12px;
}
.hint-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: var(--accent);
}
.empty-hint p {
  font-size: 14px;
}

/* 消息气泡 */
.message-bubble {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: fadeInUp 0.35s var(--ease-out) both;
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
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  color: var(--accent);
}
.avatar-ai {
  background: var(--bg-hover);
  border: 1px solid var(--border);
  color: var(--info);
}

.bubble-body {
  max-width: 75%;
}
.role-label {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.user .role-label {
  text-align: right;
}

.content {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.message-bubble.user .content {
  background: linear-gradient(135deg, rgba(212, 148, 58, 0.14) 0%, rgba(212, 148, 58, 0.08) 100%);
  border: 1px solid var(--border-accent);
  color: var(--text-primary);
  border-top-right-radius: 4px;
}
.message-bubble.assistant .content {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-primary);
  border-top-left-radius: 4px;
}

/* Markdown 样式 */
.content :deep(pre) {
  background: #0A0D12;
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
</style>
