<!--
  检索链路面板 — 显示在 assistant 消息上方
  收起: entity / search_mode / results_count
  展开: query rewrite + trace + rerank scores
-->
<template>
  <div class="retrieval-info">
    <!-- 收起状态：核心 tag -->
    <span class="tag">{{ info.results_count }} 条结果</span>
    <span v-if="info.entity" class="tag accent">主体: {{ info.entity }}</span>
    <span v-if="info.search_mode" class="tag" :class="{ warn: combinedWarn }">
      {{ combinedSearchModeLabel }}
    </span>
    <span v-if="info.rewritten_query" class="tag">改写: {{ info.rewritten_query }}</span>

    <span class="tag clickable" @click="expanded = !expanded">
      {{ expanded ? '收起' : '检索链路' }}
    </span>

    <!-- 展开状态：trace + rerank -->
    <template v-if="expanded">
      <!-- Trace 链路 -->
      <div v-if="traceRows.length" class="trace-panel">
        <div class="trace-row" v-for="row in traceRows" :key="row.label">
          <span class="trace-label">{{ row.label }}</span>
          <span v-if="row.value" class="trace-value">{{ row.value }}</span>
          <span v-if="row.ms != null" class="trace-ms">{{ row.ms }}ms</span>
        </div>
        <div class="trace-divider"></div>
        <div class="trace-row" v-if="trace?.retrieval_wall_ms != null">
          <span class="trace-label">检索总计 (wall)</span>
          <span class="trace-ms total">{{ trace.retrieval_wall_ms }}ms</span>
        </div>
        <div class="trace-row" v-if="trace?.first_token_ms != null">
          <span class="trace-label">首 Token</span>
          <span class="trace-ms">{{ trace.first_token_ms }}ms</span>
        </div>
        <div class="trace-row" v-if="trace?.generate_ms != null">
          <span class="trace-label">生成</span>
          <span class="trace-ms">{{ trace.generate_ms }}ms</span>
        </div>
        <div class="trace-divider" v-if="trace?.total_ms != null"></div>
        <div class="trace-row" v-if="trace?.total_ms != null">
          <span class="trace-label total">总耗时</span>
          <span class="trace-ms total">{{ trace.total_ms }}ms</span>
        </div>
      </div>

      <!-- Rerank 表格（现有） -->
      <div v-if="rerankItems.length" class="rerank-table-wrap">
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
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RetrievalInfo as RetrievalInfoType, RerankItem, TraceData } from '../../stores/queryChat'

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
  trace?: TraceData
}>(), {
  rerankItems: () => [],
})

const expanded = ref(false)

const resolved = computed(() => resolveSearchMode(props.info.search_mode, props.info.search_mode_hyde))
const combinedSearchModeLabel = computed(() => resolved.value.label)
const combinedWarn = computed(() => resolved.value.warn)

interface TraceRow {
  label: string
  value?: string
  ms?: number
}

const traceRows = computed<TraceRow[]>(() => {
  const t = props.trace
  if (!t) return []
  const rows: TraceRow[] = []
  if (t.entity_confirm_ms != null) rows.push({ label: '主体确认', value: props.info.entity || undefined, ms: t.entity_confirm_ms })
  if (t.rewrite_ms != null) rows.push({ label: '查询改写', value: props.info.rewritten_query || undefined, ms: t.rewrite_ms })
  if (t.search_hyde_ms != null) rows.push({ label: '搜索 + HyDE (并行)', ms: t.search_hyde_ms })
  if (t.rrf_fusion_ms != null) rows.push({ label: 'RRF 融合', ms: t.rrf_fusion_ms })
  if (t.table_expand_ms != null) rows.push({ label: '表格扩展', ms: t.table_expand_ms })
  if (t.rerank_ms != null) rows.push({ label: 'Rerank', ms: t.rerank_ms })
  if (t.post_rerank_fallback_ms != null) rows.push({ label: 'Post-rerank Fallback', ms: t.post_rerank_fallback_ms })
  if (t.build_prompt_ms != null) rows.push({ label: 'Prompt 构建', ms: t.build_prompt_ms })
  return rows
})
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

/* Trace panel */
.trace-panel {
  width: 100%;
  margin-top: 4px;
  padding: 8px 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.trace-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
  font-family: var(--font-display);
  font-size: 12px;
}

.trace-label {
  color: var(--text-secondary);
  min-width: 140px;
  flex-shrink: 0;
}
.trace-label.total {
  font-weight: 600;
  color: var(--text-primary);
}

.trace-value {
  color: var(--text-muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-ms {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  margin-left: auto;
  flex-shrink: 0;
}
.trace-ms.total {
  font-weight: 600;
  color: var(--accent);
}

.trace-divider {
  height: 1px;
  background: var(--border);
  margin: 6px 0;
}

/* Rerank table */
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
