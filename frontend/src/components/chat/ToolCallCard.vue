<!--
  工具调用折叠卡片

  显示 LangGraph 工作流中 search_context 等工具的调用结果
  默认折叠，点击展开查看完整内容
-->
<template>
  <div class="tool-call-card">
    <a-collapse :default-active-key="[]">
      <a-collapse-item :header="`工具调用: ${message.toolName}`">
        <div class="tool-content">{{ message.content }}</div>
      </a-collapse-item>
    </a-collapse>
  </div>
</template>

<script setup lang="ts">
import type { ChatMessage } from '../../stores/chat'

defineProps<{ message: ChatMessage }>()
</script>

<style scoped>
.tool-call-card {
  margin-bottom: 12px;
  max-width: 70%;
}
.tool-content {
  font-size: 13px;
  color: #4e5969;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}
</style>
