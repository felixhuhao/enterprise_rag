<!--
  知识查询聊天页主容器

  组合消息列表 + 纯文本输入框
-->
<template>
  <div class="chat-container">
    <div class="chat-toolbar">
      <div>
        <div class="toolbar-title">知识库问答工作台</div>
        <div class="toolbar-subtitle">回答会附带引用来源、检索链路和耗时追踪。</div>
      </div>
      <div class="toolbar-actions">
        <button class="debug-toggle" :class="{ active: showDebug }" @click="showDebug = !showDebug">
          调试
        </button>
        <div class="toolbar-pill">
          <span class="dot" :class="{ active: store.isStreaming }"></span>
          {{ store.isStreaming ? '生成中' : '就绪' }}
        </div>
      </div>
    </div>

    <!-- Query Debug Panel -->
    <div v-if="showDebug" class="debug-panel">
      <div class="debug-title">检索调试</div>
      <label class="debug-row">
        <span>Multi-hop 实体发现</span>
        <a-switch :model-value="store.debugConfig.use_multi_hop"
                  @change="store.debugConfig.use_multi_hop = $event as boolean" size="small" />
      </label>
      <label class="debug-row">
        <span>Groundedness 检查</span>
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

const store = useQueryChatStore()
const showDetail = ref(false)
const showDebug = ref(false)

function onSend(text: string) {
  store.sendMessage(text)
}

onBeforeUnmount(() => {
  store.stopStreaming()
})
</script>

<style scoped>
.error-bar {
  margin: 0 18px 10px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  font-family: var(--font-display);
  font-size: 12px;
}
.error-code {
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
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  animation: fadeIn 0.22s var(--ease-out);
}

.chat-toolbar {
  min-height: 58px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: var(--bg-surface);
}
.toolbar-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}
.toolbar-subtitle {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-muted);
}
.toolbar-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-secondary);
  background: var(--bg-hover);
  font-size: 12px;
  white-space: nowrap;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}
.dot.active {
  background: var(--info);
}

.toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.debug-toggle {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-muted);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.debug-toggle:hover,
.debug-toggle.active {
  color: var(--accent);
  border-color: var(--border-accent);
}

.debug-panel {
  margin: 0 18px 10px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-hover);
}

.debug-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.debug-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
}

@media (max-width: 760px) {
  .chat-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-pill {
    align-self: flex-start;
  }
}
</style>
