<!--
  知识查询聊天页主容器

  组合消息列表 + 纯文本输入框
-->
<template>
  <div class="chat-container query-console">
    <div class="chat-toolbar">
      <div class="toolbar-content">
        <div class="toolbar-caption">
          <span class="caption-eyebrow">检索模式</span>
          <span class="caption-hint">选择一种检索策略后提问</span>
        </div>
        <div class="mode-strip">
          <div class="mode-cards">
            <button
              v-for="(mode, idx) in flavorModes"
              :key="mode.id"
              class="mode-card"
              :class="{ active: store.debugConfig.retrieval_flavor === mode.id }"
              type="button"
              @click="store.debugConfig.retrieval_flavor = mode.id"
            >
              <span class="mode-index">{{ String(idx + 1).padStart(2, '0') }}</span>
              <span class="mode-copy">
                <span class="mode-name">{{ mode.name }}</span>
                <span class="mode-desc">{{ mode.desc }}</span>
              </span>
            </button>
          </div>
          <div class="mode-tools">
            <label class="evidence-toggle">
              <span>仅基于资料回答</span>
              <a-switch :model-value="store.debugConfig.strict_evidence"
                        @change="store.debugConfig.strict_evidence = $event as boolean" size="small" />
            </label>
            <button class="debug-toggle" :class="{ active: showDebug }" @click="showDebug = !showDebug">
              调试
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Query Debug Panel -->
    <div v-if="showDebug" class="debug-panel">
      <div class="debug-title">检索调试</div>
      <label class="debug-row">
        <span>资料支持度检查</span>
        <a-switch :model-value="store.debugConfig.use_groundedness"
                  @change="store.debugConfig.use_groundedness = $event as boolean" size="small" />
      </label>
    </div>

    <QueryMessageList :messages="store.messages" />

    <!-- 错误提示 -->
    <div v-if="store.error" class="error-bar">
      <span class="error-code">{{ store.error.code }}</span>
      <span class="error-hint">{{ store.error.hint }}</span>
      <span class="error-detail" @click="showDetail = !showDetail">
        {{ showDetail ? '收起' : '详情' }}
      </span>
      <div v-if="showDetail" class="error-msg">{{ store.error.message }}</div>
    </div>

    <!-- 底部输入框 -->
    <QueryChatInput
      :disabled="store.isStreaming"
      @send="onSend"
      @stop="store.stopStreaming()"
    />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useQueryChatStore } from '../../stores/queryChat'
import QueryMessageList from './QueryMessageList.vue'
import QueryChatInput from './QueryChatInput.vue'
import { FLAVOR_OPTIONS } from '../../utils/labelMaps'

const store = useQueryChatStore()
const showDetail = ref(false)
const showDebug = ref(false)
const flavorModes = FLAVOR_OPTIONS

function onSend(text: string) {
  store.sendMessage(text)
}

onBeforeUnmount(() => {
  store.stopStreaming()
})
</script>

<style scoped>
/* ============================================================
   "Instrument" — scoped Query console design language.
   Tokens are re-pointed here so child components (message list,
   telemetry, citations) inherit the new palette via the cascade.
   Nothing outside the Query view is affected.
   ============================================================ */
.query-console {
  /* Signature palette: warm paper · graphite ink · deep cobalt · cyan live */
  --qc-paper: #f4f2ed;
  --qc-surface: #fdfcf9;
  --qc-ink: #1c1a16;
  --qc-ink-2: #4c4940;
  --qc-ink-3: #8d887b;
  --qc-line: #e7e2d8;
  --qc-line-2: #d6d0c2;
  --qc-cobalt: #2a43d0;
  --qc-cobalt-hover: #1f33b0;
  --qc-cobalt-soft: #eceffc;
  --qc-cobalt-edge: #cdd4f7;
  --qc-cobalt-glow: rgba(42, 67, 208, 0.16);
  --qc-live: #0891b2;
  --qc-grid: rgba(28, 26, 22, 0.045);

  /* Re-point shared tokens used by descendant components */
  --accent: var(--qc-cobalt);
  --accent-hover: var(--qc-cobalt-hover);
  --accent-active: #16258a;
  --accent-subtle: var(--qc-cobalt-soft);
  --accent-glow: var(--qc-cobalt-glow);
  --accent-dim: #aab6f5;
  --border-accent: var(--qc-cobalt-edge);
  --text-accent: var(--qc-cobalt-hover);
  --bg-surface: var(--qc-surface);
  --bg-hover: #f0ede5;
  --border: var(--qc-line);
  --border-hover: var(--qc-line-2);
  --text-primary: var(--qc-ink);
  --text-secondary: var(--qc-ink-2);
  --text-muted: var(--qc-ink-3);
}

.error-bar {
  margin: 0 20px 12px;
  padding: 9px 14px;
  background: #fdf1f1;
  border: 1px solid #f3cdcd;
  border-left: 3px solid var(--danger);
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: 12px;
}
.error-code {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--danger, #f06060);
  margin-right: 8px;
}
.error-hint {
  color: var(--text-secondary);
}
.error-detail {
  float: right;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}
.error-detail:hover {
  color: var(--text-primary);
}
.error-msg {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(240, 96, 96, 0.15);
  color: var(--text-muted);
  font-size: 11px;
  word-break: break-all;
}

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--qc-paper);
  border: 1px solid var(--qc-line-2);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  animation: fadeIn 0.28s var(--ease-out);
}

.chat-toolbar {
  padding: 14px 20px 16px;
  border-bottom: 1px solid var(--qc-line);
  background: var(--qc-surface);
}

.toolbar-caption {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 11px;
}
.caption-eyebrow {
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--qc-cobalt);
}
.caption-eyebrow::before {
  content: "";
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 7px;
  border-radius: 1px;
  background: var(--qc-cobalt);
  transform: rotate(45deg);
  vertical-align: middle;
}
.caption-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.evidence-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 35px;
  padding: 0 12px;
  border: 1px solid var(--qc-line-2);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
  background: var(--qc-paper);
  transition: border-color 0.15s ease;
}
.evidence-toggle:hover {
  border-color: var(--qc-cobalt-edge);
}

.mode-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px;
  gap: 10px;
  align-items: start;
}

.mode-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(170px, 1fr));
  gap: 10px;
}

.mode-tools {
  display: grid;
  gap: 8px;
}

.mode-card {
  position: relative;
  display: flex;
  gap: 10px;
  min-height: 62px;
  padding: 10px 12px 10px 11px;
  border: 1px solid var(--qc-line-2);
  border-radius: var(--radius-md);
  background: var(--qc-surface);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  transition: border-color 0.18s var(--ease-out), background 0.18s var(--ease-out),
    box-shadow 0.18s var(--ease-out), transform 0.18s var(--ease-out);
}
/* left signal rail */
.mode-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--qc-cobalt);
  transform: scaleY(0);
  transform-origin: top;
  transition: transform 0.2s var(--ease-out);
}

.mode-card:hover {
  border-color: var(--qc-cobalt-edge);
  background: #fbfaf6;
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.mode-card.active {
  border-color: var(--qc-cobalt);
  background: var(--qc-cobalt-soft);
  box-shadow: 0 0 0 1px var(--qc-cobalt) inset, var(--shadow-sm);
}
.mode-card.active::before {
  transform: scaleY(1);
}

.mode-index {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
  color: var(--qc-ink-3);
  font-variant-numeric: tabular-nums;
}
.mode-card.active .mode-index {
  color: var(--qc-cobalt);
}

.mode-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.mode-name {
  display: block;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
  white-space: nowrap;
}

.mode-card.active .mode-name {
  color: var(--qc-cobalt-hover);
}

.mode-desc {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.debug-toggle {
  border: 1px solid var(--qc-line-2);
  background: var(--qc-paper);
  color: var(--text-muted);
  border-radius: var(--radius-md);
  padding: 4px 12px;
  font-family: var(--font-body);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.debug-toggle:hover,
.debug-toggle.active {
  color: var(--qc-cobalt);
  border-color: var(--qc-cobalt-edge);
  background: var(--qc-cobalt-soft);
}

.debug-panel {
  margin: 12px 20px 0;
  padding: 11px 16px;
  border: 1px solid var(--qc-line);
  border-left: 3px solid var(--qc-cobalt-edge);
  border-radius: var(--radius-md);
  background: var(--qc-surface);
}

.debug-title {
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.debug-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-primary);
}

.debug-row > span {
  white-space: nowrap;
}

@media (max-width: 760px) {
  .mode-strip {
    grid-template-columns: 1fr;
  }

  .mode-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mode-tools {
    grid-template-columns: 1fr auto;
  }
}
</style>
