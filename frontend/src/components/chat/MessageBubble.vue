<!--
  消息气泡组件

  根据 role 区分样式：
  - user: 蓝色背景，靠右显示
  - assistant: 灰色背景，靠左显示，内容通过 marked 渲染 Markdown
-->
<template>
  <div :class="['message-bubble', message.role]">
    <!-- 头像 -->
    <div class="avatar">
      <a-avatar v-if="message.role === 'user'" :size="32">U</a-avatar>
      <a-avatar v-else :size="32" :style="{ backgroundColor: '#165DFF' }">AI</a-avatar>
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
}
.message-bubble.user {
  flex-direction: row-reverse;
}
.bubble-body {
  max-width: 70%;
}
.role-label {
  font-size: 12px;
  color: #86909c;
  margin-bottom: 4px;
}
.user .role-label {
  text-align: right;
}
.content {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}
.message-bubble.user .content {
  background: #165DFF;
  color: #fff;
  border-top-right-radius: 4px;
}
.message-bubble.assistant .content {
  background: #f2f3f5;
  color: #1d2129;
  border-top-left-radius: 4px;
}
/* Markdown 中的图片自适应宽度 */
.content :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}
/* Markdown 中的代码块深色背景 */
.content :deep(pre) {
  background: #1d2129;
  color: #e5e6eb;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.content :deep(code) {
  font-size: 13px;
}
.typing-hint {
  color: #86909c;
  font-style: italic;
}
</style>
