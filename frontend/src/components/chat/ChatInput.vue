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
      <!-- 图片上传按钮（不上传到服务器，仅本地读取为 base64） -->
      <a-upload
        :auto-upload="false"
        :show-file-list="false"
        accept="image/png,image/jpeg,image/jpg"
        @change="onImageSelect"
      >
        <template #upload-button>
          <a-button type="text">
            <template #icon><icon-image /></template>
          </a-button>
        </template>
      </a-upload>
      <!-- 文本输入框 -->
      <a-textarea
        v-model="text"
        :placeholder="disabled ? '处理中...' : '输入您的问题，按 Enter 发送'"
        :disabled="disabled"
        :auto-size="{ minRows: 1, maxRows: 4 }"
        @keydown.enter.exact.prevent="onSubmit"
      />
      <!-- 发送按钮 -->
      <a-button type="primary" :disabled="disabled || !text.trim()" @click="onSubmit">
        <template #icon><icon-send /></template>
      </a-button>
    </div>
    <!-- 图片预览（上传后显示，可点击关闭） -->
    <div v-if="imagePreview" class="image-preview">
      <img :src="imagePreview" alt="预览" />
      <a-button type="text" size="mini" @click="clearImage">
        <template #icon><icon-close /></template>
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconImage, IconSend, IconClose } from '@arco-design/web-vue/es/icon'

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ send: [payload: { text: string; imageBase64?: string }] }>()

const text = ref('')
const imageBase64 = ref<string | undefined>()  // base64 data URI，发送给后端
const imagePreview = ref<string | undefined>()  // 用于本地预览缩略图

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
    imageBase64.value = dataUrl   // 保存用于发送
    imagePreview.value = dataUrl  // 保存用于预览
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
  padding: 12px 24px;
  border-top: 1px solid #e5e6eb;
  background: #fff;
}
.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.input-area :deep(.arco-textarea) {
  flex: 1;
}
.image-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.image-preview img {
  height: 60px;
  border-radius: 6px;
  border: 1px solid #e5e6eb;
}
</style>
