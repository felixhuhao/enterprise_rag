<!--
  知识查询输入组件（纯文本，无图片上传）
  Enter 发送，Shift+Enter 换行，流式处理中显示停止按钮
-->
<template>
  <div class="chat-input">
    <div class="input-area" :class="{ live: disabled }">
      <span class="prompt-glyph" :class="{ pulsing: disabled }">{{ disabled ? '◆' : '›' }}</span>
      <div class="textarea-wrap">
        <a-textarea
          v-model="text"
          :placeholder="disabled ? '检索中…' : '输入您的问题，按 Enter 发送'"
          :disabled="disabled"
          :auto-size="{ minRows: 1, maxRows: 4 }"
          @keydown.enter.exact.prevent="onSubmit"
        />
      </div>
      <!-- 流式中显示停止按钮 -->
      <button
        v-if="disabled"
        type="button"
        class="send-btn active"
        @click="emit('stop')"
      >
        <icon-pause />
      </button>
      <!-- 非流式显示发送按钮 -->
      <button
        v-else
        type="button"
        class="send-btn"
        :class="{ active: text.trim() }"
        :disabled="!text.trim()"
        @click="onSubmit"
      >
        <icon-send />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconSend, IconPause } from '@arco-design/web-vue/es/icon'

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{
  send: [text: string]
  stop: []
}>()

const text = ref('')

function onSubmit() {
  const trimmed = text.value.trim()
  if (!trimmed || props.disabled) return
  emit('send', trimmed)
  text.value = ''
}
</script>

<style scoped>
.chat-input {
  padding: 14px 20px 16px;
  border-top: 1px solid var(--qc-line, var(--border));
  background: var(--qc-surface, var(--bg-surface));
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 9px;
  background: var(--qc-paper, #f8fafc);
  border: 1px solid var(--qc-line-2, var(--border));
  border-radius: var(--radius-md);
  padding: 7px 9px 7px 11px;
  transition: border-color 0.2s var(--ease-out), box-shadow 0.2s var(--ease-out),
    background 0.2s var(--ease-out);
}

.input-area:focus-within {
  border-color: var(--accent);
  background: var(--qc-surface, #fff);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

.input-area.live {
  border-color: var(--qc-live, #0891b2);
  box-shadow: 0 0 0 3px rgba(8, 145, 178, 0.14);
}

.prompt-glyph {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  color: var(--accent);
  padding-bottom: 9px;
  flex-shrink: 0;
  user-select: none;
}
.prompt-glyph.pulsing {
  color: var(--qc-live, #0891b2);
  font-size: 10px;
  padding-bottom: 11px;
  animation: livePulse 1s ease-in-out infinite;
}
@keyframes livePulse {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

.textarea-wrap {
  flex: 1;
}
.textarea-wrap :deep(.arco-textarea-wrapper) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
.textarea-wrap :deep(.arco-textarea-wrapper:focus-within) {
  box-shadow: none !important;
}
.textarea-wrap :deep(textarea) {
  color: var(--text-primary);
}

.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: var(--qc-surface, var(--bg-surface));
  border: 1px solid var(--qc-line-2, var(--border));
  color: var(--text-muted);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s var(--ease-out);
  flex-shrink: 0;
}
.send-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  box-shadow: 0 1px 2px var(--accent-glow);
}
.send-btn.active:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  transform: translateY(-1px);
}
</style>
