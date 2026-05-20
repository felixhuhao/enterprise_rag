<!--
  消息气泡组件

  根据 role 区分样式：
  - user: 琥珀金背景，靠右显示
  - assistant: 深色背景，靠左显示，内容通过 marked 渲染 Markdown
-->
<template>
  <div :class="['message-bubble', message.role]">
    <!-- 头像 -->
    <div class="avatar">
      <div v-if="message.role === 'user'" class="avatar-user">U</div>
      <div v-else class="avatar-ai">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M8 1L14.9282 5V13L8 17L1.07179 13V5L8 1Z" fill="currentColor" opacity="0.3"/>
          <path d="M8 4L12.3301 6.5V11.5L8 14L3.66987 11.5V6.5L8 4Z" fill="currentColor"/>
        </svg>
      </div>
    </div>
    <!-- 消息体 -->
    <div class="bubble-body">
      <div class="role-label">{{ message.role === 'user' ? '你' : 'AI 助手' }}</div>
      <!-- v-html: AI 回复经 marked 渲染为 HTML（含图片、代码块等） -->
      <div class="content" v-html="renderedContent"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { ChatMessage } from '../../stores/chat'

const props = defineProps<{ message: ChatMessage }>()

// 将 Markdown 文本渲染为 HTML，并经过 DOMPurify 消毒防止 XSS
const renderedContent = computed(() => {
  if (!props.message.content) {
    return '<span class="typing-hint">思考中...</span>'
  }
  const raw = marked.parse(props.message.content) as string
  return DOMPurify.sanitize(raw)
})
</script>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: fadeInUp 0.35s var(--ease-out) both;
}
.message-bubble.user {
  flex-direction: row-reverse;
}

/* ---- Avatar ---- */
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

/* ---- Bubble ---- */
.bubble-body {
  max-width: 70%;
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

/* Markdown — images */
.content :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-sm);
  margin: 4px 0;
}

/* Markdown — code blocks */
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
.content :deep(code) {
  font-size: 13px;
}
.content :deep(:not(pre) > code) {
  background: var(--bg-hover);
  border: 1px solid var(--border);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}

/* Markdown — links */
.content :deep(a) {
  color: var(--info);
  text-decoration: none;
  border-bottom: 1px solid rgba(91, 156, 246, 0.3);
  transition: border-color 0.2s;
}
.content :deep(a:hover) {
  border-bottom-color: var(--info);
}

/* Markdown — blockquote */
.content :deep(blockquote) {
  border-left: 3px solid var(--accent-dim);
  margin: 8px 0;
  padding: 4px 12px;
  color: var(--text-secondary);
}

/* Markdown — headings */
.content :deep(h1),
.content :deep(h2),
.content :deep(h3) {
  font-family: var(--font-display);
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--text-primary);
}

/* Markdown — lists */
.content :deep(ul),
.content :deep(ol) {
  padding-left: 20px;
}
.content :deep(li) {
  margin: 4px 0;
}

.typing-hint {
  color: var(--text-muted);
  font-style: italic;
  animation: fadeIn 0.5s ease-in-out infinite alternate;
}
</style>
