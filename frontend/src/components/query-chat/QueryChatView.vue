<!--
  知识查询聊天页主容器

  组合消息列表 + 纯文本输入框
-->
<template>
  <div class="chat-container">
    <!-- 消息列表 -->
    <QueryMessageList :messages="store.messages" />

    <!-- 错误提示 -->
    <div v-if="store.error" class="error-bar">
      <span class="error-code">{{ store.error.code }}</span>
      <span class="error-hint">{{ store.error.hint }}</span>
      <span class="error-detail" @click="showDetail = !showDetail">
        {{ showDetail ? '收起' : '详情' }}
      </span>
      <div v-if="showDetail" class="error-msg">{{ store.error.message }}</div>
    </div>

    <!-- 底部输入框 -->
    <QueryChatInput
      :disabled="store.isStreaming"
      @send="onSend"
      @stop="store.stopStreaming()"
    />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useQueryChatStore } from '../../stores/queryChat'
import QueryMessageList from './QueryMessageList.vue'
import QueryChatInput from './QueryChatInput.vue'

const store = useQueryChatStore()
const showDetail = ref(false)

function onSend(text: string) {
  store.sendMessage(text)
}

onBeforeUnmount(() => {
  store.stopStreaming()
})
</script>

<style scoped>
.error-bar {
  margin: 0 16px 8px;
  padding: 8px 12px;
  background: rgba(240, 96, 96, 0.08);
  border: 1px solid rgba(240, 96, 96, 0.2);
  border-radius: 8px;
  font-family: var(--font-display);
  font-size: 12px;
}
.error-code {
  font-weight: 600;
  color: var(--danger, #f06060);
  margin-right: 8px;
}
.error-hint {
  color: var(--text-secondary);
}
.error-detail {
  float: right;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}
.error-detail:hover {
  color: var(--text-primary);
}
.error-msg {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(240, 96, 96, 0.15);
  color: var(--text-muted);
  font-size: 11px;
  word-break: break-all;
}

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  animation: fadeIn 0.3s var(--ease-out);
}
</style>
