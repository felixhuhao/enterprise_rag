<!--
  消息列表组件

  根据消息类型分发到 MessageBubble（用户/AI）或 ToolCallCard（工具调用）
-->
<template>
  <div class="message-list" ref="listRef">
    <!-- 空状态提示 -->
    <div class="empty-hint" v-if="messages.length === 0">
      <a-empty description="开始对话吧" />
    </div>
    <!-- 渲染每条消息 -->
    <div v-for="msg in messages" :key="msg.id">
      <MessageBubble v-if="msg.role !== 'tool'" :message="msg" />
      <ToolCallCard v-else :message="msg" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { ChatMessage } from '../../stores/chat'
import MessageBubble from './MessageBubble.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps<{ messages: ChatMessage[] }>()

// 列表容器引用，用于自动滚动到底部
const listRef = ref<HTMLDivElement>()

// 监听消息列表长度变化，自动滚到底部
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    scrollToBottom()
  },
)

function scrollToBottom() {
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}

defineExpose({ scrollToBottom })
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}
.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>
