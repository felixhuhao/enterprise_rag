<template>
  <div class="section-label">总体</div>
  <div class="stats-cards stagger">
    <div class="stat-card" v-for="item in cards" :key="item.label">
      <div class="stat-value">{{ formatValue(item) }}</div>
      <div class="stat-label">{{ item.label }}</div>
    </div>
  </div>

  <section v-if="flavorRows.length || strictRows.length" class="metric-section">
    <a-tabs default-active-key="flavor" size="small" animation>
      <a-tab-pane key="flavor" title="按策略">
        <div class="metric-table">
          <div class="metric-row metric-header">
            <span>策略</span>
            <span>查询数</span>
            <span>成功率</span>
            <span>平均结果</span>
            <span>平均相关性重排</span>
            <span>P95 延迟</span>
            <span>扩大范围</span>
          </div>
          <div class="metric-row" v-for="row in flavorRows" :key="row.key">
            <strong>{{ row.label }}</strong>
            <span>{{ row.stats.count }}</span>
            <span>{{ formatPercent(row.stats.success_rate) }}</span>
            <span>{{ formatNumber(row.stats.avg_results, 1) }}</span>
            <span>{{ formatNumber(row.stats.avg_rerank, 3) }}</span>
            <span>{{ formatMs(row.stats.p95_ms) }}</span>
            <span>{{ formatPercent(row.stats.fallback_ratio) }}</span>
          </div>
        </div>
      </a-tab-pane>
      <a-tab-pane key="strict" title="按证据模式">
        <div class="metric-table">
          <div class="metric-row metric-header">
            <span>证据策略</span>
            <span>查询数</span>
            <span>成功率</span>
            <span>平均结果</span>
            <span>平均相关性重排</span>
            <span>P95 延迟</span>
            <span>扩大范围</span>
          </div>
          <div class="metric-row" v-for="row in strictRows" :key="row.key">
            <strong>{{ row.label }}</strong>
            <span>{{ row.stats.count }}</span>
            <span>{{ formatPercent(row.stats.success_rate) }}</span>
            <span>{{ formatNumber(row.stats.avg_results, 1) }}</span>
            <span>{{ formatNumber(row.stats.avg_rerank, 3) }}</span>
            <span>{{ formatMs(row.stats.p95_ms) }}</span>
            <span>{{ formatPercent(row.stats.fallback_ratio) }}</span>
          </div>
        </div>
      </a-tab-pane>
    </a-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type {
  FlavorMetric,
  QueryStats,
  QueryStatsByFlavor,
  QueryStatsByStrict,
} from '../../api/queryStats'
import { FLAVOR_KEYS, STRICT_MODE_LABELS, flavorLabel } from '../../utils/labelMaps'

const props = defineProps<{
  stats: QueryStats | null
  byFlavor?: QueryStatsByFlavor | null
  byStrict?: QueryStatsByStrict | null
}>()

const emptyMetric: FlavorMetric = {
  count: 0,
  success_count: 0,
  failed_count: 0,
  success_rate: 0,
  avg_rerank: 0,
  avg_results: 0,
  p95_ms: 0,
  fallback_count: 0,
  fallback_ratio: 0,
}

const cards = computed(() => {
  const s = props.stats
  if (!s) return []
  return [
    { label: '总查询数', value: s.total_queries, precision: 0 },
    { label: '成功率', value: formatPercent(1 - s.failure_rate) },
    { label: '平均结果数', value: s.avg_result_count, precision: 1 },
    { label: '平均相关性重排', value: s.avg_rerank_score, precision: 3 },
    { label: 'P95 延迟', value: formatMs(s.p95_ms) },
    { label: '扩大范围比例', value: formatPercent(s.fallback_ratio) },
  ]
})

const flavorRows = computed<Array<{ key: string; label: string; stats: FlavorMetric }>>(() => {
  const stats = props.byFlavor
  if (!stats) return []
  return FLAVOR_KEYS.map((key) => ({
    key,
    label: flavorLabel(key),
    stats: stats[key] ?? emptyMetric,
  }))
})

const strictRows = computed<Array<{ key: string; label: string; stats: FlavorMetric }>>(() => {
  const stats = props.byStrict
  if (!stats) return []
  return (['non_strict', 'strict'] as const).map((key) => ({
    key,
    label: STRICT_MODE_LABELS[key],
    stats: stats[key] ?? emptyMetric,
  }))
})

function formatPercent(rate: number): string {
  return (rate * 100).toFixed(1) + '%'
}

function formatValue(item: { value: number | string; precision?: number }) {
  if (typeof item.value === 'string') return item.value
  return formatNumber(item.value, item.precision ?? 0)
}

function formatNumber(value: number, precision: number) {
  return precision > 0 ? value.toFixed(precision) : String(value)
}

function formatMs(ms: number): string {
  if (!ms) return '0ms'
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return `${ms}ms`
}
</script>

<style scoped>
.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(155px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.section-label {
  margin: 0 0 8px;
  color: var(--text-secondary);
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
}

.stat-card {
  position: relative;
  overflow: hidden;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  transition: border-color 0.15s var(--ease-out), background 0.15s var(--ease-out);
}

.stat-card:hover {
  border-color: var(--border-hover);
  background: #f8fafc;
}

.stat-value {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-label {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  margin-top: 6px;
}

.metric-section {
  margin-bottom: 18px;
}

.metric-section :deep(.arco-tabs-content) {
  padding-top: 8px;
}

.metric-table {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-surface);
}

.metric-row {
  display: grid;
  grid-template-columns: minmax(92px, 1.2fr) repeat(6, minmax(76px, 1fr));
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 9px 12px;
  border-top: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
}

.metric-row:first-child {
  border-top: 0;
}

.metric-row strong {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
}

.metric-row span:not(:first-child) {
  font-variant-numeric: tabular-nums;
}

.metric-header {
  min-height: 36px;
  background: #f8fafc;
  color: var(--text-muted);
  font-family: var(--font-display);
  font-weight: 700;
}

@media (max-width: 900px) {
  .metric-table {
    overflow-x: auto;
  }

  .metric-row {
    min-width: 720px;
  }
}
</style>
