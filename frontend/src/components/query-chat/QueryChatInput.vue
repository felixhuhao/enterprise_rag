<!--
  知识查询输入组件（纯文本，无图片上传）
  Enter 发送，Shift+Enter 换行，流式处理中显示停止按钮
-->
<template>
  <div class="chat-input">
    <div class="input-area">
      <div class="textarea-wrap">
        <a-textarea
          v-model="text"
          :placeholder="disabled ? '检索中...' : '输入您的问题，按 Enter 发送'"
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
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg-surface);
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 6px 8px;
  transition: border-color 0.2s var(--ease-out), box-shadow 0.2s var(--ease-out);
}

.input-area:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-glow);
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
  width: 34px;
  height: 34px;
  border: none;
  background: var(--bg-hover);
  color: var(--text-muted);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s var(--ease-out);
  flex-shrink: 0;
}
.send-btn.active {
  background: var(--accent);
  color: #0B0E14;
  box-shadow: var(--shadow-glow);
}
.send-btn.active:hover {
  transform: scale(1.05);
}
</style>
