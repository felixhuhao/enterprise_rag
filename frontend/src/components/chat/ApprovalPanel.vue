<!--
  人工审批面板

  当 LangGraph 工作流评估分数在 0.6~0.8 之间时触发中断，
  显示此面板让用户选择：
  - 认可：接受当前 AI 回复
  - 不认可：拒绝当前回复，系统将通过网络搜索重新生成
-->
<template>
  <div class="approval-panel">
    <div class="approval-alert">
      <div class="alert-icon">⚠</div>
      <div class="alert-text">
        AI 回复评估分数: <strong>{{ score?.toFixed(2) }}</strong>，需要人工审批
      </div>
    </div>
    <div class="approval-actions">
      <button class="approve-btn" @click="$emit('approve')">认可</button>
      <button class="reject-btn" @click="$emit('reject')">不认可（重新搜索）</button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ score: number | null }>()
defineEmits<{ approve: []; reject: [] }>()
</script>

<style scoped>
.approval-panel {
  padding: 14px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg-surface);
  animation: fadeInUp 0.3s var(--ease-out);
}

.approval-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: rgba(232, 168, 56, 0.08);
  border: 1px solid rgba(232, 168, 56, 0.2);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 14px;
}

.alert-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.alert-text strong {
  color: var(--warning);
  font-family: var(--font-display);
}

.approval-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  justify-content: center;
}

.approve-btn,
.reject-btn {
  padding: 8px 24px;
  border-radius: var(--radius-sm);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s var(--ease-out);
  border: none;
}

.approve-btn {
  background: var(--accent);
  color: #0B0E14;
}
.approve-btn:hover {
  background: var(--accent-hover);
  box-shadow: var(--shadow-glow);
}

.reject-btn {
  background: rgba(240, 96, 96, 0.1);
  border: 1px solid rgba(240, 96, 96, 0.3);
  color: var(--danger);
}
.reject-btn:hover {
  background: rgba(240, 96, 96, 0.18);
}
</style>
