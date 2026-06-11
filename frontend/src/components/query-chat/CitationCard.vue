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
      <div v-for="c in citations" :key="c.id" class="citation-item" :class="{ clickable: c.document_id }" @click="openDocument(c)">
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
            v-for="imgPath in visibleImagePaths(c)"
            :key="imgPath"
            :src="imageObjectUrl(c.document_id, imgPath)"
            class="citation-thumb"
            loading="lazy"
            @click="openImagePreview(c.document_id, imgPath)"
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
import { onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { IconBookmark, IconDown, IconImage } from '@arco-design/web-vue/es/icon'
import type { Citation } from '../../stores/queryChat'
import apiClient from '../../api/client'

const props = defineProps<{ citations: Citation[] }>()
const expanded = ref(false)
const previewSrc = ref('')
const imageUrls = ref<Record<string, string>>({})
const router = useRouter()
let loadVersion = 0

function openDocument(citation: Citation) {
  if (citation.document_id) {
    router.push({
      path: `/documents/${citation.document_id}`,
      query: highlightQuery(citation),
    })
  }
}

function highlightQuery(citation: Citation) {
  if (citation.chunk_key) return { highlight_chunk_key: citation.chunk_key }
  if (citation.chunk_id != null) return { highlight_chunk: String(citation.chunk_id) }
  return undefined
}

function imageObjectUrl(documentId: string, imagePath: string): string {
  return imageUrls.value[imageKey(documentId, imagePath)] || ''
}

function visibleImagePaths(citation: Citation): string[] {
  const documentId = citation.document_id
  if (!documentId) return []
  return (citation.image_paths || [])
    .slice(0, 3)
    .filter((imagePath) => imageObjectUrl(documentId, imagePath))
}

function openImagePreview(documentId: string, imagePath: string) {
  const url = imageObjectUrl(documentId, imagePath)
  if (url) previewSrc.value = url
}

function imageKey(documentId: string, imagePath: string): string {
  return `${documentId}::${imagePath}`
}

function assetApiPath(documentId: string, imagePath: string): string {
  const normalized = imagePath.replace(/\\/g, '/')
  const idx = normalized.indexOf(`/${documentId}/`)
  const relativePath = idx >= 0 ? normalized.slice(idx + documentId.length + 2) : normalized
  const encodedPath = relativePath.split('/').map(encodeURIComponent).join('/')
  return `/documents/${documentId}/assets/${encodedPath}`
}

async function loadCitationImages() {
  const version = ++loadVersion
  clearImageUrls()
  const nextUrls: Record<string, string> = {}

  for (const citation of props.citations) {
    if (!citation.document_id || !citation.image_paths?.length) continue
    for (const imagePath of citation.image_paths.slice(0, 3)) {
      try {
        const res = await apiClient.get(assetApiPath(citation.document_id, imagePath), {
          responseType: 'blob',
        })
        const objectUrl = URL.createObjectURL(res.data)
        if (version !== loadVersion) {
          URL.revokeObjectURL(objectUrl)
          continue
        }
        nextUrls[imageKey(citation.document_id, imagePath)] = objectUrl
      } catch {
        // Ignore broken citation thumbnails; the textual citation remains visible.
      }
    }
  }

  if (version === loadVersion) {
    imageUrls.value = nextUrls
  } else {
    for (const url of Object.values(nextUrls)) URL.revokeObjectURL(url)
  }
}

function clearImageUrls() {
  for (const url of Object.values(imageUrls.value)) URL.revokeObjectURL(url)
  imageUrls.value = {}
  if (previewSrc.value.startsWith('blob:')) previewSrc.value = ''
}

watch(() => props.citations, () => { void loadCitationImages() }, { deep: true, immediate: true })
onUnmounted(clearImageUrls)
</script>

<style scoped>
.citation-card {
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-surface);
}

.citation-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 12px;
  background: var(--bg-hover);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  transition: color 0.2s, background 0.2s;
}
.citation-header:hover {
  color: var(--accent);
  background: var(--accent-subtle);
}
.citation-header .rotated {
  transform: rotate(180deg);
}
.citation-header span {
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  font-variant-numeric: tabular-nums;
}
.citation-header > :last-child {
  margin-left: auto;
  transition: transform 0.2s var(--ease-out);
}

.citation-list {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--border);
}

.citation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.citation-item.clickable {
  cursor: pointer;
}
.citation-item.clickable:hover {
  color: var(--text-primary);
}

.citation-id {
  font-weight: 600;
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 7px;
  border-radius: var(--radius-sm);
  background: var(--accent-subtle);
  border: 1px solid var(--border-accent);
  flex-shrink: 0;
}

.citation-field {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-image-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: var(--info);
  margin-left: auto;
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
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: transform 0.15s, border-color 0.15s;
}
.citation-thumb:hover {
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
