<!--
  检索步骤信息 — 显示在 assistant 消息上方
-->
<template>
  <div class="retrieval-info">
    <span class="tag">{{ info.results_count }} 条结果</span>
    <span v-if="info.entity" class="tag accent">实体: {{ info.entity }}</span>
    <span v-if="info.rewritten_query" class="tag">改写: {{ info.rewritten_query }}</span>
  </div>
</template>

<script setup lang="ts">
import type { RetrievalInfo as RetrievalInfoType } from '../../stores/queryChat'

defineProps<{ info: RetrievalInfoType }>()
</script>

<style scoped>
.retrieval-info {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}

.tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font-display);
  letter-spacing: 0.02em;
}
.tag.accent {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--accent-subtle);
}
</style>
