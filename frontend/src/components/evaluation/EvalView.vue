<!--
  回归评测 — 基准测试集运行、结果查看，admin-only。
-->
<template>
  <div class="eval-page">
    <EvalRunPanel />
  </div>
</template>

<script setup lang="ts">
import EvalRunPanel from '../evaluate/EvalRunPanel.vue'
</script>

<style scoped>
.eval-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}
</style>
