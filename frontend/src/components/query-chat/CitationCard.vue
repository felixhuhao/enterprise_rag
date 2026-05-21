<!--
  引用卡片 — assistant 消息下方折叠展示
-->
<template>
  <div class="citation-card">
    <div class="citation-header" @click="expanded = !expanded">
      <icon-bookmark />
      <span>引用来源 ({{ citations.length }})</span>
      <icon-down :class="{ rotated: expanded }" />
    </div>
    <div v-if="expanded" class="citation-list">
      <div v-for="c in citations" :key="c.id" class="citation-item">
        <span class="citation-id">{{ c.id }}</span>
        <span v-if="c.file_title" class="citation-field">{{ c.file_title }}</span>
        <span v-if="c.section_title" class="citation-field">{{ c.section_title }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconBookmark, IconDown } from '@arco-design/web-vue/es/icon'
import type { Citation } from '../../stores/queryChat'

defineProps<{ citations: Citation[] }>()
const expanded = ref(false)
</script>

<style scoped>
.citation-card {
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.citation-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--bg-hover);
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
  transition: color 0.2s;
}
.citation-header:hover {
  color: var(--accent);
}
.citation-header .rotated {
  transform: rotate(180deg);
}
.citation-header span {
  font-family: var(--font-display);
  letter-spacing: 0.02em;
}

.citation-list {
  padding: 6px 10px;
}

.citation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.citation-id {
  font-weight: 600;
  color: var(--info);
  font-family: var(--font-display);
  font-size: 11px;
}

.citation-field {
  color: var(--text-muted);
}
</style>
