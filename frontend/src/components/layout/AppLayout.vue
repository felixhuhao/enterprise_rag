<!--
  应用主布局

  左侧导航栏（可折叠）+ 顶部标题栏 + 主内容区
  侧边栏底部提供 Token 输入（不依赖 API，直接写 localStorage）
-->
<template>
  <a-layout class="app-layout">
    <!-- 左侧导航栏 -->
    <a-layout-sider :width="220" :collapsible="true" class="sider">
      <div class="logo">港股交易规则 AI 助手</div>
      <a-menu :selected-keys="[currentRoute]" @menu-item-click="onMenuClick">
        <a-menu-item key="/chat">
          <template #icon><icon-message /></template>
          智能对话
        </a-menu-item>
        <a-menu-item key="/knowledge">
          <template #icon><icon-book /></template>
          知识库管理
        </a-menu-item>
        <a-menu-item key="/evaluate">
          <template #icon><icon-bar-chart /></template>
          评估看板
        </a-menu-item>
        <a-menu-item key="/settings">
          <template #icon><icon-settings /></template>
          系统设置
        </a-menu-item>
      </a-menu>
      <!-- Token 输入区域（固定在侧边栏底部，无需 API 鉴权） -->
      <div class="sider-footer">
        <div class="token-label" @click="showTokenInput = !showTokenInput">
          <icon-lock />
          <span>API Token</span>
          <icon-tag v-if="tokenSet && !showTokenInput" :style="{ color: '#00b42a' }" />
        </div>
        <div v-if="showTokenInput" class="token-input">
          <a-input-password
            v-model="tokenValue"
            placeholder="输入 API Token"
            size="small"
            @keydown.enter="saveToken"
          />
          <a-button type="primary" size="mini" @click="saveToken">保存</a-button>
        </div>
      </div>
    </a-layout-sider>
    <!-- 右侧主区域 -->
    <a-layout>
      <a-layout-header class="header">
        <span class="header-title">多模态 RAG 知识库</span>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  IconMessage,
  IconBook,
  IconBarChart,
  IconSettings,
  IconLock,
  IconTag,
} from '@arco-design/web-vue/es/icon'

const router = useRouter()
const route = useRoute()

const currentRoute = computed(() => route.path)
const showTokenInput = ref(false)
const tokenValue = ref('')
const tokenSet = ref(false)

function onMenuClick(key: string) {
  router.push(key)
}

onMounted(() => {
  const stored = localStorage.getItem('api_token')
  if (stored) {
    tokenValue.value = stored
    tokenSet.value = true
  } else {
    showTokenInput.value = true
  }
})

function saveToken() {
  const trimmed = tokenValue.value.trim()
  if (!trimmed) return
  localStorage.setItem('api_token', trimmed)
  tokenSet.value = true
  showTokenInput.value = false
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
}
.sider {
  background: #fff;
  border-right: 1px solid #e5e6eb;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
  color: #1d2129;
  border-bottom: 1px solid #e5e6eb;
}
.sider-footer {
  margin-top: auto;
  border-top: 1px solid #e5e6eb;
  padding: 12px 16px;
}
.token-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #86909c;
  cursor: pointer;
  user-select: none;
}
.token-label:hover {
  color: #165DFF;
}
.token-input {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.token-input :deep(.arco-input-password) {
  flex: 1;
}
.header {
  background: #fff;
  border-bottom: 1px solid #e5e6eb;
  display: flex;
  align-items: center;
  padding: 0 24px;
  height: 52px;
}
.header-title {
  font-size: 15px;
  color: #86909c;
}
.content {
  background: #f7f8fa;
  padding: 16px;
  overflow: hidden;
}
</style>
