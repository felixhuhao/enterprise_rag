<!--
  引用卡片 — assistant 消息下方折叠展示
-->
<template>
  <div class="citation-card">
    <div class="citation-header" @click="expanded = !expanded">
      <icon-bookmark />
      <span>引用来源 ({{ citations.length }})</span>
      <icon-down :class="{ rotated: expanded }" />
    </div>
    <div v-if="expanded" class="citation-list">
      <div v-for="c in citations" :key="c.id" class="citation-item">
        <span class="citation-id">{{ c.id }}</span>
        <span v-if="c.file_title" class="citation-field">{{ c.file_title }}</span>
        <span v-if="c.section_title" class="citation-field">{{ c.section_title }}</span>
        <span v-if="c.image_paths?.length" class="citation-image-badge" title="含图片引用">
          <icon-image /> {{ c.image_paths.length }}
        </span>
      </div>
      <!-- 图片缩略图 -->
      <template v-for="c in citations" :key="'img-' + c.id">
        <div v-if="c.image_paths?.length && c.document_id" class="citation-images">
          <img
            v-for="imgPath in c.image_paths.slice(0, 3)"
            :key="imgPath"
            :src="assetUrl(c.document_id, imgPath)"
            class="citation-thumb"
            loading="lazy"
            @click="previewSrc = assetUrl(c.document_id, imgPath)"
            @error="($event.target as HTMLImageElement).style.display = 'none'"
          />
        </div>
      </template>
    </div>
    <!-- 图片预览 -->
    <div v-if="previewSrc" class="preview-overlay" @click="previewSrc = ''">
      <img :src="previewSrc" class="preview-img" @click.stop />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { IconBookmark, IconDown, IconImage } from '@arco-design/web-vue/es/icon'
import type { Citation } from '../../stores/queryChat'

defineProps<{ citations: Citation[] }>()
const expanded = ref(false)
const previewSrc = ref('')

function assetUrl(documentId: string, imagePath: string): string {
  // Backend serves: GET /api/documents/{document_id}/assets/{asset_path:path}?token=xxx
  const normalized = imagePath.replace(/\\/g, '/')
  // Absolute path: extract part after /{document_id}/
  const idx = normalized.indexOf(`/${documentId}/`)
  const relativePath = idx >= 0 ? normalized.slice(idx + documentId.length + 2) : normalized
  const token = localStorage.getItem('api_token') || ''
  return `/api/documents/${documentId}/assets/${relativePath}${token ? `?token=${encodeURIComponent(token)}` : ''}`
}
</script>

<style scoped>
.citation-card {
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.citation-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--bg-hover);
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
  transition: color 0.2s;
}
.citation-header:hover {
  color: var(--accent);
}
.citation-header .rotated {
  transform: rotate(180deg);
}
.citation-header span {
  font-family: var(--font-display);
  letter-spacing: 0.02em;
}

.citation-list {
  padding: 6px 10px;
}

.citation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.citation-id {
  font-weight: 600;
  color: var(--info);
  font-family: var(--font-display);
  font-size: 11px;
}

.citation-field {
  color: var(--text-muted);
}

.citation-image-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: var(--accent);
  opacity: 0.8;
}

.citation-images {
  display: flex;
  gap: 6px;
  padding: 4px 0 6px;
}

.citation-thumb {
  width: 80px;
  height: 60px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--border);
  cursor: pointer;
  transition: transform 0.15s, border-color 0.15s;
}
.citation-thumb:hover {
  transform: scale(1.05);
  border-color: var(--accent);
}

.preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  cursor: pointer;
}

.preview-img {
  max-width: 90vw;
  max-height: 85vh;
  border-radius: 6px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.5);
}
</style>
