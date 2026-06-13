<template>
  <section class="overview-section">
    <div class="section-head">
      <div>
        <h3>整体表现</h3>
        <p>当前筛选范围内的在线查询质量指标。</p>
      </div>
    </div>
    <div class="stats-cards">
      <div
        class="stat-card"
        :class="{ primary: index === 0 }"
        v-for="(item, index) in cards"
        :key="item.label"
      >
        <div class="stat-label">{{ item.label }}</div>
        <div class="stat-value">{{ formatValue(item) }}</div>
      </div>
    </div>
  </section>

  <section v-if="flavorRows.length || strictRows.length" class="metric-layout">
    <div v-if="flavorRows.length" class="metric-section primary">
      <div class="section-head compact">
        <div>
          <h3>按策略</h3>
          <p>不同检索策略的延迟和质量不能混在一起判断。</p>
        </div>
      </div>
      <div class="metric-table">
        <div class="metric-row metric-header">
          <span>策略</span>
          <span>查询数</span>
          <span>成功率</span>
          <span>平均结果</span>
          <span>Rerank</span>
          <span>P95 延迟</span>
        </div>
        <div class="metric-row" v-for="row in flavorRows" :key="row.key">
          <strong>{{ row.label }}</strong>
          <span>{{ row.stats.count }}</span>
          <span>{{ formatPercent(row.stats.success_rate) }}</span>
          <span>{{ formatNumber(row.stats.avg_results, 1) }}</span>
          <span>{{ formatNumber(row.stats.avg_rerank, 3) }}</span>
          <span>{{ formatMs(row.stats.p95_ms) }}</span>
        </div>
      </div>
    </div>

    <div v-if="strictRows.length" class="metric-section secondary">
      <div class="section-head compact">
        <div>
          <h3>证据模式</h3>
          <p>普通回答与仅基于资料回答分开看。</p>
        </div>
      </div>
      <div class="strict-cards">
        <div v-for="row in strictRows" :key="row.key" class="strict-card">
          <div>
            <strong>{{ row.label }}</strong>
            <span>{{ row.stats.count }} 次</span>
          </div>
          <dl>
            <div>
              <dt>成功率</dt>
              <dd>{{ formatPercent(row.stats.success_rate) }}</dd>
            </div>
            <div>
              <dt>Rerank</dt>
              <dd>{{ formatNumber(row.stats.avg_rerank, 3) }}</dd>
            </div>
            <div>
              <dt>P95</dt>
              <dd>{{ formatMs(row.stats.p95_ms) }}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  </section>

  <details v-if="flavorRows.length || strictRows.length" class="raw-metrics">
    <summary>更多聚合指标</summary>
    <div class="raw-metric-grid">
      <div v-if="flavorRows.length" class="metric-table compact-table">
        <div class="metric-row metric-header">
          <span>策略</span>
          <span>扩大范围</span>
          <span>失败数</span>
        </div>
        <div class="metric-row" v-for="row in flavorRows" :key="row.key">
          <strong>{{ row.label }}</strong>
          <span :class="{ 'metric-zero': !row.stats.fallback_ratio }">{{ formatPercent(row.stats.fallback_ratio) }}</span>
          <span :class="{ 'metric-zero': !row.stats.failed_count }">{{ row.stats.failed_count }}</span>
        </div>
      </div>
      <div v-if="strictRows.length" class="metric-table compact-table">
        <div class="metric-row metric-header">
          <span>证据模式</span>
          <span>扩大范围</span>
          <span>失败数</span>
        </div>
        <div class="metric-row" v-for="row in strictRows" :key="row.key">
          <strong>{{ row.label }}</strong>
          <span :class="{ 'metric-zero': !row.stats.fallback_ratio }">{{ formatPercent(row.stats.fallback_ratio) }}</span>
          <span :class="{ 'metric-zero': !row.stats.failed_count }">{{ row.stats.failed_count }}</span>
        </div>
      </div>
    </div>
  </details>
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
    { label: 'Rerank', value: s.avg_rerank_score, precision: 3 },
    { label: 'P95 延迟', value: formatMs(s.p95_ms) },
    { label: '扩大范围', value: formatPercent(s.fallback_ratio) },
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
.overview-section,
.metric-section,
.raw-metrics {
  margin-bottom: 16px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.section-head h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 700;
}

.section-head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.section-head.compact {
  margin-bottom: 8px;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  position: relative;
  overflow: hidden;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 16px 15px;
  box-shadow: var(--shadow-sm);
}
/* top hairline — neutral by default, cobalt on the hero card */
.stat-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  height: 2px;
  background: var(--border-hover);
}
.stat-card.primary {
  background: linear-gradient(170deg, var(--accent-subtle), var(--bg-surface) 62%);
  border-color: var(--border-accent);
}
.stat-card.primary::before {
  background: linear-gradient(90deg, var(--accent), var(--accent-dim));
}

.stat-label {
  font-family: var(--font-body);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-muted);
}

.stat-value {
  font-family: var(--font-display);
  font-size: 25px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  line-height: 1.15;
  margin-top: 7px;
  font-variant-numeric: tabular-nums;
}
.stat-card.primary .stat-value {
  color: var(--accent);
}

.metric-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(280px, 0.9fr);
  gap: 14px;
  align-items: start;
  margin-bottom: 12px;
}

.metric-table {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}

.metric-row {
  display: grid;
  grid-template-columns: minmax(90px, 1.15fr) repeat(5, minmax(72px, 1fr));
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 8px 14px;
  border-top: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 12px;
  transition: background 0.12s var(--ease-out);
}

.metric-row:not(.metric-header):hover {
  background: var(--bg-hover);
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

/* zero/empty values recede so real numbers carry the eye */
.metric-zero {
  color: var(--text-muted);
  opacity: 0.55;
}

.metric-header {
  min-height: 36px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-family: var(--font-display);
  font-weight: 700;
  letter-spacing: 0.01em;
}
.metric-header:hover {
  background: var(--bg-subtle);
}

.strict-cards {
  display: grid;
  gap: 8px;
}

.strict-card {
  display: grid;
  gap: 11px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}

.strict-card > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--border);
}

.strict-card strong {
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
}

.strict-card span {
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.strict-card dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.strict-card dl div {
  min-width: 0;
}

.strict-card dt {
  color: var(--text-muted);
  font-size: 11px;
}

.strict-card dd {
  margin: 4px 0 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
}

.raw-metrics {
  padding: 11px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.raw-metrics summary {
  display: flex;
  align-items: center;
  cursor: pointer;
  list-style: none;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.raw-metrics summary::-webkit-details-marker {
  display: none;
}

.raw-metrics summary::after {
  margin-left: auto;
  color: var(--text-muted);
  font-weight: 400;
  content: '展开';
}

.raw-metrics[open] summary::after {
  content: '收起';
}

.raw-metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.compact-table .metric-row {
  grid-template-columns: minmax(100px, 1fr) repeat(2, minmax(72px, 0.7fr));
}

@media (max-width: 900px) {
  .stats-cards,
  .metric-layout,
  .raw-metric-grid {
    grid-template-columns: 1fr;
  }

  .stats-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-table {
    overflow-x: auto;
  }

  .metric-row {
    min-width: 620px;
  }
}
</style>
