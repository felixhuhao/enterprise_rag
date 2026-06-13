<template>
  <div>
    <div v-if="!isAdmin" class="readonly-note">当前用户没有修改权限。</div>
    <div class="strategy-note">
      当前版本仍使用一组全局参数；这里按后端 planner 展示每种策略真正会使用的部分。固定预算只读显示，避免产生“改了但不生效”的误解。
    </div>

    <a-tabs :active-key="activeFlavor" size="small" class="strategy-tabs" animation @change="onFlavorTabChange">
      <a-tab-pane v-for="profile in strategyProfiles" :key="profile.key" :title="profile.label">
        <div class="capability-band">
          <div class="profile-heading compact">
            <div class="profile-desc">{{ profile.description }}</div>
            <a-tooltip :content="profile.reason">
              <span class="profile-debug">plan</span>
            </a-tooltip>
          </div>
          <div class="capability-list">
            <div v-for="item in activeCapabilities" :key="item.key" class="capability-chip" :class="{ off: !item.enabled }">
              <span class="status-dot" />
              <span>{{ item.label }}</span>
              <small>{{ item.enabled ? '开启' : '关闭' }}</small>
            </div>
          </div>
        </div>

        <div class="metric-strip">
          <div v-for="item in activeBudget" :key="item.label" class="metric-item">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>

        <section class="settings-section">
          <div v-if="activeControls.length" class="compact-section-title">可调预算</div>
          <div v-if="activeControls.length" class="parameter-grid">
            <label v-for="control in activeControls" :key="control.key" class="parameter-field">
              <span>{{ control.label }}</span>
              <a-input-number
                :model-value="form[control.key]"
                :min="control.min"
                :max="control.max"
                :disabled="!isAdmin"
                @update:model-value="updateFormValue(control.key, $event)"
              />
            </label>
          </div>
          <div v-else class="fixed-note">该策略的检索预算固定为上方显示值。</div>
        </section>
      </a-tab-pane>
    </a-tabs>

    <details class="global-weights">
      <summary>
        <span>全局权重</span>
        <small>影响底层检索与重排，不按策略单独区分</small>
      </summary>
      <div class="weight-grid">
        <label class="compact-slider">
          <span>语义权重 {{ numberValue('denseWeight').toFixed(2) }}</span>
          <a-slider :model-value="form.denseWeight" :min="0" :max="1" :step="0.05" :disabled="!isAdmin" @update:model-value="updateFormValue('denseWeight', $event)" />
        </label>
        <label class="compact-slider">
          <span>关键词权重 {{ numberValue('sparseWeight').toFixed(2) }}</span>
          <a-slider :model-value="form.sparseWeight" :min="0" :max="1" :step="0.05" :disabled="!isAdmin" @update:model-value="updateFormValue('sparseWeight', $event)" />
        </label>
        <label class="compact-slider">
          <span>LLM 重排权重 {{ numberValue('rerankLlmWeight').toFixed(2) }}</span>
          <a-slider :model-value="form.rerankLlmWeight" :min="0" :max="1" :step="0.05" :disabled="!isAdmin" @update:model-value="updateFormValue('rerankLlmWeight', $event)" />
        </label>
        <label class="compact-slider">
          <span>RRF 权重 {{ numberValue('rerankRrfWeight').toFixed(2) }}</span>
          <a-slider :model-value="form.rerankRrfWeight" :min="0" :max="1" :step="0.05" :disabled="!isAdmin" @update:model-value="updateFormValue('rerankRrfWeight', $event)" />
        </label>
      </div>
    </details>

    <div class="settings-actions">
      <a-button type="primary" :loading="saving" :disabled="!isAdmin" @click="$emit('save')">
        保存策略微调
      </a-button>
      <a-button :loading="loading" @click="$emit('reload')">恢复当前值</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
type FlavorKey = 'balanced' | 'exact' | 'recall'

interface StrategyProfile {
  key: FlavorKey
  label: string
  description: string
  reason: string
}

interface BudgetControl {
  key: string
  label: string
  min: number
  max: number
}

interface CapabilityStatus {
  key: string
  label: string
  enabled: boolean
}

const props = defineProps<{
  isAdmin: boolean
  activeFlavor: FlavorKey
  strategyProfiles: StrategyProfile[]
  activeCapabilities: CapabilityStatus[]
  activeBudget: Array<{ label: string; value: string; note?: string }>
  activeControls: BudgetControl[]
  form: Record<string, any>
  saving: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  (event: 'update:activeFlavor', value: FlavorKey): void
  (event: 'updateFormValue', key: string, value: unknown): void
  (event: 'save'): void
  (event: 'reload'): void
}>()

function onFlavorTabChange(key: string | number) {
  if (['balanced', 'exact', 'recall'].includes(String(key))) {
    emit('update:activeFlavor', String(key) as FlavorKey)
  }
}

function updateFormValue(key: string, value: unknown) {
  emit('updateFormValue', key, value)
}

function numberValue(key: string) {
  const value = Number(props.form[key])
  return Number.isFinite(value) ? value : 0
}
</script>

<style scoped>
.strategy-tabs :deep(.arco-tabs-nav-tab) {
  padding-left: 0;
}

.strategy-tabs :deep(.arco-tabs-nav-tab-list) {
  padding-left: 0;
}

.strategy-tabs :deep(.arco-tabs-nav-type-line .arco-tabs-tab:first-of-type) {
  margin-left: 0 !important;
}

.readonly-note,
.fixed-note {
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: 12px;
}

.readonly-note {
  margin-bottom: 12px;
  color: #7c2d12;
  background: #fff7ed;
  border: 1px solid #fed7aa;
}

.fixed-note {
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
}

.strategy-note {
  margin: 4px 0 10px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.settings-section {
  margin-bottom: 0;
}

.compact-section-title {
  margin: 2px 0 8px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.capability-band {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.profile-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.profile-heading.compact {
  margin-bottom: 7px;
}

.profile-desc {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12px;
}

.profile-debug {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 11px;
  cursor: help;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(7, minmax(88px, 1fr));
  gap: 6px;
  margin-bottom: 10px;
}

.metric-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}

.metric-item span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}

.metric-item strong {
  color: var(--text-primary);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.parameter-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px 12px;
}

.parameter-field,
.compact-slider {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.parameter-field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 86px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}

.parameter-field span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.parameter-field :deep(.arco-input-number) {
  width: 86px;
}

.compact-slider span {
  flex: 0 0 138px;
  white-space: nowrap;
}

.compact-slider :deep(.arco-slider) {
  flex: 1;
  min-width: 120px;
}

.capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
}

.capability-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 3px 8px;
  border: 1px solid #bbf7d0;
  border-radius: 999px;
  background: #f0fdf4;
  color: var(--text-secondary);
  font-size: 12px;
}

.capability-chip.off {
  border-color: var(--border);
  background: var(--bg-hover);
  color: var(--text-muted);
}

.capability-chip small {
  color: #166534;
  font-size: 11px;
}

.capability-chip.off small {
  color: var(--text-muted);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #22c55e;
}

.capability-chip.off .status-dot {
  background: #cbd5e1;
}

.global-weights {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.global-weights summary {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  list-style: none;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.global-weights summary::-webkit-details-marker {
  display: none;
}

.global-weights summary small {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}

.global-weights summary::after {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
  content: '展开';
}

.global-weights[open] summary::after {
  content: '收起';
}

.weight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 8px 18px;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}

.settings-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .metric-strip,
  .parameter-grid,
  .weight-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .profile-heading {
    flex-direction: column;
  }

  .metric-strip,
  .parameter-grid,
  .weight-grid {
    grid-template-columns: 1fr;
  }

  .parameter-field,
  .compact-slider {
    align-items: stretch;
    flex-direction: column;
  }

  .parameter-field span,
  .compact-slider span {
    flex: none;
  }

  .parameter-field,
  .parameter-field :deep(.arco-input-number) {
    width: 100%;
  }
}
</style>
