<!--
  知识查询聊天页主容器

  组合消息列表 + 纯文本输入框
  V1: 不做图片上传、审批、工具调用
-->
<template>
  <div class="chat-container">
    <!-- 消息列表 -->
    <QueryMessageList
      :messages="store.messages"
      :retrieval-info="store.retrievalInfo"
      :rerank-items="store.rerankDebug"
    />

    <!-- 底部输入框 -->
    <QueryChatInput
      :disabled="store.isStreaming"
      @send="onSend"
    />
  </div>
</template>

<script setup lang="ts">
import { useQueryChatStore } from '../../stores/queryChat'
import QueryMessageList from './QueryMessageList.vue'
import QueryChatInput from './QueryChatInput.vue'

const store = useQueryChatStore()

function onSend(text: string) {
  store.sendMessage(text)
}
</script>

<style scoped>
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
