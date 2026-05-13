<!--
  聊天页主容器

  组合三个子组件：消息列表、审批面板、输入框
  挂载时自动初始化会话
-->
<template>
  <div class="chat-container">
    <!-- 消息列表（支持滚动） -->
    <MessageList :messages="chatStore.messages" />

    <!-- 审批面板：仅在评估分数 0.6~0.8 触发中断时显示 -->
    <ApprovalPanel
      v-if="chatStore.isInterrupted"
      :score="chatStore.interruptScore"
      @approve="chatStore.approveOrReject('approve')"
      @reject="chatStore.approveOrReject('reject')"
    />

    <!-- 底部输入框：文本 + 图片上传 -->
    <ChatInput
      :disabled="chatStore.isStreaming"
      @send="onSend"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useChatStore } from '../../stores/chat'
import MessageList from './MessageList.vue'
import ApprovalPanel from './ApprovalPanel.vue'
import ChatInput from './ChatInput.vue'

const chatStore = useChatStore()

// 页面挂载时自动创建会话
onMounted(() => {
  chatStore.initSession()
})

// 转发 ChatInput 的 send 事件到 store
function onSend({ text, imageBase64 }: { text: string; imageBase64?: string }) {
  chatStore.sendMessage(text, imageBase64)
}
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}
</style>
