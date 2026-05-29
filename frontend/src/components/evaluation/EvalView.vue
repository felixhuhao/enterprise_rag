<!--
  回归评测 — Golden Set 运行、结果查看，admin-only。
-->
<template>
  <div class="eval-page">
    <div class="eval-header">
      <h3>回归评测</h3>
      <p>运行 Golden Set 验证当前配置下的回答质量和引用命中率。</p>
    </div>
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
.eval-header { margin-bottom: 16px; }
.eval-header h3 { margin: 0; font-size: 18px; font-weight: 700; color: var(--text-primary); }
.eval-header p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; }
</style>
