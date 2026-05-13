<!--
  人工审批面板

  当 LangGraph 工作流评估分数在 0.6~0.8 之间时触发中断，
  显示此面板让用户选择：
  - 认可：接受当前 AI 回复
  - 不认可：拒绝当前回复，系统将通过网络搜索重新生成
-->
<template>
  <div class="approval-panel">
    <a-alert type="warning" :closable="false">
      <template #message>
        AI 回复评估分数: <strong>{{ score?.toFixed(2) }}</strong>，需要人工审批
      </template>
    </a-alert>
    <div class="approval-actions">
      <a-button type="primary" @click="$emit('approve')">认可</a-button>
      <a-button status="danger" @click="$emit('reject')">不认可（重新搜索）</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ score: number | null }>()
defineEmits<{ approve: []; reject: [] }>()
</script>

<style scoped>
.approval-panel {
  padding: 12px 24px;
  border-top: 1px solid #e5e6eb;
  background: #fff;
}
.approval-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  justify-content: center;
}
</style>
