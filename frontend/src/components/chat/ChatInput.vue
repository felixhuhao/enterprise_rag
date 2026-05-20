<!--
  聊天输入组件

  支持：
  - 文本输入（a-textarea，Enter 发送，Shift+Enter 换行）
  - 图片上传（转为 base64 data URI 传给后端）
  - 图片预览（上传后显示缩略图，可删除）
  - 流式处理中禁用输入
-->
<template>
  <div class="chat-input">
    <div class="input-area">
      <!-- 图片上传按钮 -->
      <a-upload
        :auto-upload="false"
        :show-file-list="false"
        accept="image/png,image/jpeg,image/jpg"
        @change="onImageSelect"
      >
        <template #upload-button>
          <button type="button" class="icon-btn" :disabled="disabled" title="上传图片">
            <icon-image />
          </button>
        </template>
      </a-upload>
      <!-- 文本输入框 -->
      <div class="textarea-wrap">
        <a-textarea
          v-model="text"
          :placeholder="disabled ? '处理中...' : '输入您的问题，按 Enter 发送'"
          :disabled="disabled"
          :auto-size="{ minRows: 1, maxRows: 4 }"
          @keydown.enter.exact.prevent="onSubmit"
        />
      </div>
      <!-- 发送按钮 -->
      <button
        type="button"
        class="send-btn"
        :class="{ active: !disabled && text.trim() }"
        :disabled="disabled || !text.trim()"
        @click="onSubmit"
      >
        <icon-send />
      </button>
    </div>
    <!-- 图片预览 -->
    <div v-if="imagePreview" class="image-preview">
      <img :src="imagePreview" alt="预览" />
      <button type="button" class="icon-btn small" @click="clearImage">
        <icon-close />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconImage, IconSend, IconClose } from '@arco-design/web-vue/es/icon'

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ send: [payload: { text: string; imageBase64?: string }] }>()

const text = ref('')
const imageBase64 = ref<string | undefined>()
const imagePreview = ref<string | undefined>()

/** 提交消息（文本 + 可选图片） */
function onSubmit() {
  const trimmed = text.value.trim()
  if (!trimmed && !imageBase64.value) return
  if (props.disabled) return

  emit('send', { text: trimmed, imageBase64: imageBase64.value })
  text.value = ''
  clearImage()
}

/** 图片选择回调：读取文件为 base64 data URI */
function onImageSelect(fileItem: any) {
  const file = fileItem.file?.file || fileItem
  if (!(file instanceof File)) return

  const reader = new FileReader()
  reader.onload = (e) => {
    const dataUrl = e.target?.result as string
    imageBase64.value = dataUrl
    imagePreview.value = dataUrl
  }
  reader.readAsDataURL(file)
}

/** 清除已选图片 */
function clearImage() {
  imageBase64.value = undefined
  imagePreview.value = undefined
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

/* Icon button */
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s var(--ease-out);
  flex-shrink: 0;
}
.icon-btn:hover:not(:disabled) {
  color: var(--accent);
  background: var(--accent-subtle);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.icon-btn.small {
  width: 24px;
  height: 24px;
}

/* Send button */
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
.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.send-btn.active:hover {
  transform: scale(1.05);
}

/* Image preview */
.image-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.image-preview img {
  height: 56px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}
</style>
