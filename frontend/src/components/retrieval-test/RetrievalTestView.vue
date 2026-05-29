<template>
  <div class="retrieval-test-page">
    <section class="test-panel">
      <div class="query-area">
        <a-textarea
          v-model="query"
          placeholder="输入要测试的查询，例如：差旅报销需要哪些审批材料？"
          :auto-size="{ minRows: 3, maxRows: 5 }"
          allow-clear
        />
        <a-button type="primary" :loading="loading" @click="runTest">
          <template #icon><icon-search /></template>
          开始检索
        </a-button>
      </div>

      <div class="control-row">
        <label class="control-item">
          <span>查找方式</span>
          <a-select v-model="retrievalFlavor" size="small" class="flavor-select">
            <a-option value="balanced">标准问答</a-option>
            <a-option value="exact">精确查找</a-option>
            <a-option value="recall">全面查找</a-option>
            <a-option value="discovery">关联查找</a-option>
          </a-select>
        </label>
        <label class="control-item">
          <span>Top K</span>
          <a-input-number v-model="topK" :min="1" :max="30" size="small" />
        </label>
        <label class="switch-item">
          <span>混合检索</span>
          <a-switch v-model="useHybrid" size="small" />
        </label>
        <label class="switch-item">
          <span>HyDE</span>
          <a-switch v-model="useHyde" size="small" />
        </label>
        <label class="switch-item">
          <span>重排</span>
          <a-switch v-model="useRerank" size="small" />
        </label>
        <label class="switch-item">
          <span>仅基于资料回答</span>
          <a-switch v-model="strictEvidence" size="small" />
        </label>
      </div>
    </section>

    <section v-if="errorMessage" class="error-panel">
      {{ errorMessage }}
    </section>

    <template v-if="response">
      <section class="strategy-panel">
        <div class="strategy-main">
          <div>
            <h3>当前策略</h3>
            <p>{{ strategyText }}</p>
          </div>
          <div class="strategy-tags">
            <a-tag :color="response.strategy.hybrid ? 'arcoblue' : 'gray'">
              {{ response.strategy.hybrid ? 'Hybrid' : 'Dense Only' }}
            </a-tag>
            <a-tag :color="response.strategy.hyde ? 'purple' : 'gray'">
              HyDE {{ response.strategy.hyde ? '开启' : '关闭' }}
            </a-tag>
            <a-tag :color="response.strategy.rerank ? 'green' : 'gray'">
              重排 {{ response.strategy.rerank ? '开启' : '关闭' }}
            </a-tag>
            <a-tag :color="response.strategy.fallback ? 'orange' : 'gray'">
              {{ response.strategy.fallback ? '已回退' : '无回退' }}
            </a-tag>
            <a-tag v-if="response.fallback_info?.blocked" color="red">
              回退已阻止
            </a-tag>
          </div>
        </div>

        <div class="strategy-grid">
          <div class="metric">
            <span>结果数</span>
            <strong>{{ response.result_count }}</strong>
          </div>
          <div class="metric">
            <span>检索耗时</span>
            <strong>{{ response.trace.retrieval_wall_ms ?? 0 }}ms</strong>
          </div>
          <div class="metric">
            <span>实体路由</span>
            <strong>{{ entityRouteLabel }}</strong>
          </div>
          <div class="metric">
            <span>Embedding</span>
            <strong>{{ response.strategy.embedding_model }}</strong>
          </div>
          <div class="metric">
            <span>LLM</span>
            <strong>{{ response.strategy.chat_model }}</strong>
          </div>
        </div>

        <div v-if="fallbackText" class="fallback-note">
          {{ fallbackText }}
        </div>

        <!-- Per-entity hit distribution -->
        <div v-if="entityEntries.length" class="entity-dist">
          <span class="entity-dist-label">实体命中分布</span>
          <div v-for="[name, count] in entityEntries" :key="name" class="entity-dist-item">
            <span class="entity-dist-name">{{ name }}</span>
            <span class="entity-dist-count">{{ count }} 条</span>
          </div>
        </div>
      </section>

      <section class="results-panel">
        <div class="results-header">
          <div>
            <h3>Top Chunks</h3>
            <p v-if="response.rewritten_query !== response.query">
              改写查询：{{ response.rewritten_query }}
            </p>
            <p v-else>展示检索、融合、表格展开和重排后的候选 chunks。</p>
          </div>
          <div class="trace-mini">
            <span>搜索 {{ response.trace.search_hyde_ms ?? 0 }}ms</span>
            <span>融合 {{ response.trace.rrf_fusion_ms ?? 0 }}ms</span>
            <span>重排 {{ response.trace.rerank_ms ?? 0 }}ms</span>
          </div>
        </div>

        <a-table
          :data="response.results"
          :pagination="{ pageSize: 10 }"
          :bordered="false"
          row-key="rank"
          class="retrieval-table"
        >
          <template #columns>
            <a-table-column title="#" :width="58" align="center">
              <template #cell="{ record }">
                <strong>{{ record.rank }}</strong>
              </template>
            </a-table-column>

            <a-table-column title="来源" :width="260">
              <template #cell="{ record }">
                <div class="source-cell">
                  <button type="button" @click="openDocument(record.document_id)">
                    {{ record.file_title || record.document_id }}
                  </button>
                  <span>{{ record.section_title || '—' }}</span>
                </div>
              </template>
            </a-table-column>

            <a-table-column title="页码" :width="70" align="center">
              <template #cell="{ record }">
                {{ record.page ?? '—' }}
              </template>
            </a-table-column>

            <a-table-column title="路径" :width="170">
              <template #cell="{ record }">
                <a-tag color="arcoblue" size="small">{{ record.retrieval_path }}</a-tag>
              </template>
            </a-table-column>

            <a-table-column title="分数" :width="116" align="center">
              <template #cell="{ record }">
                <div class="score-cell">
                  <strong>{{ formatScore(record.final_score ?? record.score) }}</strong>
                  <span v-if="record.llm_score !== null && record.llm_score !== undefined">
                    LLM {{ formatScore(record.llm_score) }}
                  </span>
                </div>
              </template>
            </a-table-column>

            <a-table-column title="类型" :width="110" align="center">
              <template #cell="{ record }">
                <a-tag :color="sourceTypeColor(record.source_type)" size="small">
                  {{ sourceTypeLabel(record.source_type) }}
                </a-tag>
              </template>
            </a-table-column>

            <a-table-column title="内容">
              <template #cell="{ record }">
                <div class="content-cell">
                  <p>{{ expandedKeys.has(record.rank) ? record.content : record.content_preview }}</p>
                  <button
                    v-if="record.content.length > record.content_preview.length"
                    type="button"
                    @click="toggleExpand(record.rank)"
                  >
                    {{ expandedKeys.has(record.rank) ? '收起' : '展开' }}
                  </button>
                </div>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </section>
    </template>

    <a-empty v-else-if="!loading" class="empty-state" description="输入查询后运行检索测试" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { IconSearch } from '@arco-design/web-vue/es/icon'

defineOptions({ name: 'RetrievalTestView' })
import type { RetrievalTestResponse } from '../../api/retrievalTest'
import { runRetrievalTest } from '../../api/retrievalTest'

const router = useRouter()

const query = ref('差旅报销需要哪些审批材料？')
const topK = ref(10)
const retrievalFlavor = ref('balanced')
const useHybrid = ref(true)
const useHyde = ref(true)
const useRerank = ref(true)
const strictEvidence = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const response = ref<RetrievalTestResponse | null>(null)
const expandedKeys = ref<Set<number>>(new Set())

const strategyText = computed(() => {
  if (!response.value) return ''
  const s = response.value.strategy
  const weights = s.hybrid ? `Dense ${s.dense_weight} / Sparse ${s.sparse_weight}` : 'Dense 1.0'
  return `Top ${s.top_k}，${weights}，主检索：${s.search_mode || '—'}，HyDE：${s.search_mode_hyde || '—'}`
})

const entityRouteLabel = computed(() => {
  if (!response.value) return '—'
  const mode = response.value.entity_mode
  const entity = response.value.confirmed_entity
  if (mode === 'single') return entity || '—'
  if (mode === 'multi_explicit') {
    const entities = response.value.matched_entities ?? []
    return entities.join(' / ')
  }
  if (mode === 'broad') return '全局检索'
  return entity || '全库'
})

const entityEntries = computed(() => {
  if (!response.value?.per_entity_counts) return []
  return Object.entries(response.value.per_entity_counts)
})

const fallbackText = computed(() => {
  const info = response.value?.fallback_info
  if (!info?.used && !info?.blocked) return ''
  const scope = filterToScope(info.original_filter)
  if (info.used) return `${scope} -> 全部资料：原范围证据不足，已扩大查找范围。`
  return `${scope}：当前模式禁止扩大到全部资料。`
})

async function runTest() {
  const trimmed = query.value.trim()
  if (!trimmed) {
    Message.warning('请输入查询内容')
    return
  }
  loading.value = true
  errorMessage.value = ''
  expandedKeys.value = new Set()
  try {
    response.value = await runRetrievalTest({
      query: trimmed,
      top_k: topK.value,
      use_hybrid: useHybrid.value,
      use_hyde: useHyde.value,
      use_rerank: useRerank.value,
      retrieval_flavor: retrievalFlavor.value,
      strict_evidence: strictEvidence.value,
    })
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    errorMessage.value = detail || err?.message || '检索测试失败'
  } finally {
    loading.value = false
  }
}

function toggleExpand(rank: number) {
  const next = new Set(expandedKeys.value)
  if (next.has(rank)) {
    next.delete(rank)
  } else {
    next.add(rank)
  }
  expandedKeys.value = next
}

function openDocument(documentId: string) {
  if (!documentId) return
  router.push(`/documents/${documentId}`)
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  return Number(value).toFixed(3)
}

function sourceTypeColor(sourceType: string) {
  return sourceType.startsWith('table_') ? 'orange' : 'arcoblue'
}

function sourceTypeLabel(sourceType: string) {
  const map: Record<string, string> = {
    text: '文本',
    table_summary: '表格摘要',
    table_full: '完整表格',
    table_row_group: '表格行组',
  }
  return map[sourceType] ?? (sourceType || '未知')
}

function filterToScope(filter: string) {
  const matched = filter.match(/entity_name == "([^"]+)"/)
  return matched?.[1] || '原实体范围'
}
</script>

<style scoped>
.retrieval-test-page {
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.test-panel,
.strategy-panel,
.results-panel,
.error-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px;
}

.query-area {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: flex-start;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.control-item,
.switch-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.control-item :deep(.arco-input-number) {
  width: 92px;
}

.flavor-select {
  width: 132px;
}

.error-panel {
  margin-top: 14px;
  color: var(--error);
  background: #fff5f5;
  border-color: rgba(220, 38, 38, 0.2);
}

.strategy-panel {
  margin-top: 14px;
}

.strategy-main,
.results-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.strategy-main h3,
.results-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}

.strategy-main p,
.results-header p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.strategy-tags {
  display: inline-flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.strategy-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.metric {
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  min-width: 0;
}

.metric span {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
}

.metric strong {
  display: block;
  margin-top: 6px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.results-panel {
  margin-top: 14px;
}

.entity-dist {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  align-items: center;
}

.fallback-note {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #92400e;
  font-size: 12px;
}

.entity-dist-label {
  font-size: 12px;
  color: var(--text-muted);
}

.entity-dist-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  font-size: 12px;
}

.entity-dist-name {
  color: var(--accent);
  font-weight: 500;
}

.entity-dist-count {
  color: var(--text-muted);
}

.trace-mini {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--text-muted);
  font-size: 12px;
}

.trace-mini span {
  border: 1px solid var(--border);
  background: var(--bg-hover);
  border-radius: 999px;
  padding: 4px 8px;
}

.retrieval-table {
  margin-top: 14px;
}

.source-cell {
  min-width: 0;
}

.source-cell button {
  display: block;
  max-width: 230px;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--accent);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.source-cell span {
  display: block;
  margin-top: 4px;
  max-width: 230px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.score-cell strong,
.score-cell span {
  display: block;
}

.score-cell strong {
  color: var(--text-primary);
  font-size: 13px;
}

.score-cell span {
  color: var(--text-muted);
  font-size: 11px;
}

.content-cell {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.content-cell p {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.content-cell button {
  flex: 0 0 auto;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 5px 8px;
}

.content-cell button:hover {
  color: var(--accent);
  border-color: var(--border-accent);
}

.empty-state {
  margin-top: 60px;
}

@media (max-width: 1100px) {
  .strategy-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .query-area {
    grid-template-columns: 1fr;
  }

  .strategy-main,
  .results-header {
    flex-direction: column;
  }

  .strategy-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
