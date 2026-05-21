<!--
  检索步骤信息 — 显示在 assistant 消息上方
-->
<template>
  <div class="retrieval-info">
    <span class="tag">{{ info.results_count }} 条结果</span>
    <span v-if="info.entity" class="tag accent">实体: {{ info.entity }}</span>
    <span v-if="info.search_mode" class="tag" :class="{ warn: combinedWarn }">
      {{ combinedSearchModeLabel }}
    </span>
    <span v-if="info.rewritten_query" class="tag">改写: {{ info.rewritten_query }}</span>

    <!-- rerank 折叠 -->
    <span
      v-if="rerankItems.length"
      class="tag clickable"
      @click="showRerank = !showRerank"
    >
      {{ showRerank ? '收起' : '证据评分' }}
    </span>

    <div v-if="showRerank && rerankItems.length" class="rerank-table-wrap">
      <table class="rerank-table">
        <thead>
          <tr>
            <th>#</th>
            <th>文件</th>
            <th>章节</th>
            <th>类型</th>
            <th>LLM</th>
            <th>RRF</th>
            <th>综合</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rerankItems" :key="item.index">
            <td>{{ item.index }}</td>
            <td class="cell-ellipsis" :title="item.file_title">{{ item.file_title }}</td>
            <td class="cell-ellipsis" :title="item.section_title">{{ item.section_title || '—' }}</td>
            <td>{{ item.source_type }}</td>
            <td>{{ item.llm_score }}</td>
            <td>{{ item.rrf_score }}</td>
            <td class="cell-score">{{ item.final_score }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RetrievalInfo as RetrievalInfoType, RerankItem } from '../../stores/queryChat'

/** 优先级：post_rerank > fallback > filtered > base */
function resolveSearchMode(mode: string, modeHyde: string): { label: string; warn: boolean } {
  const all = [mode, modeHyde].filter(Boolean)
  const hasPattern = (p: string) => all.some(s => s.includes(p))

  if (hasPattern('post_rerank_fallback')) return { label: '混合搜索(Rerank回退)', warn: true }
  if (hasPattern('fallback')) return { label: '混合搜索(回退全量)', warn: true }
  if (hasPattern('filtered')) return { label: '混合搜索(已过滤)', warn: false }
  if (all.length > 0) return { label: '混合搜索', warn: false }
  return { label: '', warn: false }
}

const props = withDefaults(defineProps<{
  info: RetrievalInfoType
  rerankItems?: RerankItem[]
}>(), {
  rerankItems: () => [],
})

const showRerank = ref(false)

const resolved = computed(() => resolveSearchMode(props.info.search_mode, props.info.search_mode_hyde))
const combinedSearchModeLabel = computed(() => resolved.value.label)
const combinedWarn = computed(() => resolved.value.warn)
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
.tag.warn {
  color: var(--warning, #faad14);
  border-color: var(--warning, #faad14);
  background: rgba(250, 173, 20, 0.08);
}
.tag.clickable {
  cursor: pointer;
  user-select: none;
}
.tag.clickable:hover {
  background: var(--bg-active);
}

.rerank-table-wrap {
  width: 100%;
  overflow-x: auto;
  margin-top: 4px;
}

.rerank-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-family: var(--font-display);
}

.rerank-table th,
.rerank-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}

.rerank-table th {
  color: var(--text-muted);
  font-weight: 500;
}

.rerank-table td {
  color: var(--text-secondary);
}

.cell-ellipsis {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-score {
  font-weight: 600;
  color: var(--text-primary);
}
</style>
