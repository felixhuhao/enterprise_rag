<template>
  <div class="not-found">
    <div class="not-found-title">页面不存在</div>
    <div class="not-found-desc">当前地址没有对应页面。</div>
    <a-button type="primary" @click="router.replace('/query-chat')">返回知识查询</a-button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.not-found {
  display: flex;
  min-height: 260px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
}

.not-found-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.not-found-desc {
  margin-bottom: 6px;
  color: var(--text-muted);
}
</style>
