<!--
  知识查询聊天页主容器

  组合消息列表 + 纯文本输入框
-->
<template>
  <div class="chat-container">
    <div class="chat-toolbar">
      <div class="toolbar-content">
        <div class="toolbar-head">
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
        <div class="mode-strip">
          <button
            v-for="mode in flavorModes"
            :key="mode.id"
            class="mode-card"
            :class="{ active: store.debugConfig.retrieval_flavor === mode.id }"
            type="button"
            @click="store.debugConfig.retrieval_flavor = mode.id"
          >
            <span class="mode-name">{{ mode.name }}</span>
            <span class="mode-desc">{{ mode.desc }}</span>
          </button>
          <label class="evidence-toggle">
            <span>仅基于资料回答</span>
            <a-switch :model-value="store.debugConfig.strict_evidence"
                      @change="store.debugConfig.strict_evidence = $event as boolean" size="small" />
          </label>
        </div>
      </div>
    </div>

    <!-- Query Debug Panel -->
    <div v-if="showDebug" class="debug-panel">
      <div class="debug-title">检索调试</div>
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
const flavorModes = [
  { id: 'balanced', name: '标准问答', desc: '平衡速度和准确率，适合日常资料问答' },
  { id: 'exact', name: '精确查找', desc: '优先匹配条款、金额、日期和明确事实' },
  { id: 'recall', name: '全面查找', desc: '扩大召回范围，适合模糊或同义表达' },
  { id: 'discovery', name: '关联查找', desc: '先发现相关实体，再按实体查找证据' },
]

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
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
}

.toolbar-content {
  display: grid;
  gap: 10px;
}

.toolbar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
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

.evidence-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 58px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
  background: var(--bg-hover);
}

.mode-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(118px, 1fr)) auto;
  gap: 8px;
  align-items: stretch;
}

.mode-card {
  min-height: 58px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.mode-card:hover {
  border-color: var(--border-hover);
  background: #f8fafc;
}

.mode-card.active {
  border-color: var(--accent);
  background: var(--accent-subtle);
}

.mode-name {
  display: block;
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
  white-space: nowrap;
}

.mode-card.active .mode-name {
  color: var(--accent);
}

.mode-desc {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 15px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
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
  margin: 10px 18px 0;
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
  gap: 12px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-primary);
}

.debug-row > span {
  white-space: nowrap;
}

@media (max-width: 760px) {
  .toolbar-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-pill {
    align-self: flex-start;
  }

  .mode-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evidence-toggle {
    justify-content: space-between;
    grid-column: 1 / -1;
  }
}
</style>
