<template>
  <div v-if="visibleTags.length" class="chunk-tags" :title="tagTitle">
    <span v-for="tag in visibleTags" :key="tag.value" class="chunk-tag">
      {{ tag.label }}
    </span>
    <span v-if="hiddenCount" class="chunk-tag more">
      +{{ hiddenCount }}
    </span>
  </div>
  <span v-else class="muted-text">—</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { structuredTagLabel } from '../../utils/labelMaps'

const props = withDefaults(defineProps<{
  structured_tags?: string[] | null
  keywords?: string[] | null
  maxVisible?: number
}>(), {
  maxVisible: 3,
})

function uniqueStrings(values: string[] | null | undefined) {
  return Array.from(new Set((values ?? []).filter(Boolean)))
}

const structuredTags = computed(() => uniqueStrings(props.structured_tags))
const keywordTags = computed(() => uniqueStrings(props.keywords))
const visibleTags = computed(() => structuredTags.value.slice(0, props.maxVisible).map((value) => ({
  value,
  label: structuredTagLabel(value),
})))
const hiddenCount = computed(() => Math.max(0, structuredTags.value.length - visibleTags.value.length))
const tagTitle = computed(() => {
  const parts = []
  if (structuredTags.value.length) {
    parts.push(`标签：${structuredTags.value.map(structuredTagLabel).join(' / ')}`)
  }
  if (keywordTags.value.length) {
    parts.push(`关键词：${keywordTags.value.join(' / ')}`)
  }
  return parts.join('\n')
})
</script>

<style scoped>
.chunk-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: flex-start;
}

.chunk-tag {
  max-width: 100%;
  padding: 2px 6px;
  border-radius: 999px;
  color: #166534;
  background: #dcfce7;
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chunk-tag.more {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.muted-text {
  color: var(--text-muted);
}
</style>
