<template>
  <section class="settings-section">
    <div class="section-heading">
      <div>
        <div class="section-title">访问令牌</div>
        <div class="section-hint">更新后立即写入本地请求 Token，并调用后端持久化。</div>
      </div>
      <span class="section-kicker">Admin</span>
    </div>
    <div class="token-row">
      <a-input-password
        v-model="tokenValue"
        placeholder="输入新的访问令牌"
        allow-clear
        :disabled="!isAdmin"
      />
      <a-button type="primary" :loading="saving" :disabled="!isAdmin" @click="$emit('save')">
        更新
      </a-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modelValue: string
  isAdmin: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
  (event: 'save'): void
}>()

const tokenValue = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', String(value ?? '')),
})
</script>

<style scoped>
.settings-section {
  margin-bottom: 0;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.section-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.section-hint {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12px;
}

.section-kicker {
  flex-shrink: 0;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
  font-size: 11px;
}

.token-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

@media (max-width: 760px) {
  .section-heading {
    flex-direction: column;
  }

  .token-row {
    grid-template-columns: 1fr;
  }
}
</style>
