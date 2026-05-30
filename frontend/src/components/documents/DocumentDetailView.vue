<template>
  <div class="document-detail-page">
    <button class="back-link" type="button" @click="goBack">
      <icon-left />
      返回文档列表
    </button>

    <a-spin :loading="loading" class="detail-spin">
      <template v-if="document">
        <section class="detail-card">
          <div class="detail-header">
            <div class="document-title">
              <icon-file class="document-icon" :style="{ color: document.file_type === 'pdf' ? 'var(--error)' : 'var(--accent)' }" />
              <span :title="document.filename">{{ document.filename }}</span>
            </div>
            <div class="status-stack">
              <a-tag
                v-if="document.cleanup_status === 'milvus_delete_failed'"
                color="orangered"
                size="small"
              >
                待清理
              </a-tag>
              <a-tag v-else :color="statusColor(document.status)" size="small">
                {{ statusLabel(document.status) }}
              </a-tag>
              <a-tag :color="chunkSourceColor" size="small">
                {{ chunkSourceLabel }}
              </a-tag>
            </div>
          </div>

          <div class="metadata-grid">
            <div class="metadata-item">
              <span>文件类型</span>
              <strong>{{ document.file_type.toUpperCase() }}</strong>
            </div>
            <div class="metadata-item">
              <span>文档主体</span>
              <strong>{{ document.entity_name || '—' }}</strong>
            </div>
            <div class="metadata-item">
              <span>Chunks</span>
              <strong>{{ chunks.length }}</strong>
            </div>
            <div class="metadata-item">
              <span>图片</span>
              <strong>{{ document.image_count || 0 }}</strong>
            </div>
            <div class="metadata-item">
              <span>上传时间</span>
              <strong>{{ formatTime(document.created_at) }}</strong>
            </div>
            <div class="metadata-item">
              <span>更新时间</span>
              <strong>{{ formatTime(document.updated_at) }}</strong>
            </div>
          </div>

          <div v-if="document.error_msg || document.error_code" class="error-panel">
            <span v-if="document.error_code" class="error-code">{{ document.error_code }}</span>
            <span>{{ errorHint || document.error_msg }}</span>
          </div>
        </section>

        <section class="detail-card chunks-card">
          <div class="chunks-toolbar">
            <div>
              <h3>Chunk 列表</h3>
              <p>{{ filteredChunks.length }} / {{ chunks.length }} 个 chunks</p>
            </div>
            <a-input-search
              v-model="keyword"
              class="chunk-search"
              placeholder="搜索 chunk 内容"
              allow-clear
            />
          </div>

          <a-table
            :data="filteredChunks"
            :pagination="{ pageSize: PAGE_SIZE, current: currentPage }"
            :bordered="false"
            row-key="chunk_key"
            :row-class="rowClass"
            @page-change="onPageChange"
            class="chunk-table"
            size="small"
            column-resizable
            @column-resize="chunkColumns.onColumnResize"
          >
            <template #columns>
              <a-table-column title="#" data-index="sequence" :width="chunkColumns.columnWidth('sequence')" align="center" :body-cell-class="bodyCellClass">
                <template #cell="{ record }">
                  {{ record.sequence }}
                </template>
              </a-table-column>

              <a-table-column title="章节" data-index="section_title" :width="chunkColumns.columnWidth('section_title')" :body-cell-class="bodyCellClass">
                <template #cell="{ record }">
                  <span class="section-cell" :title="record.section_title || record.title">
                    {{ record.section_title || record.title || '—' }}
                  </span>
                </template>
              </a-table-column>

              <a-table-column title="页码" data-index="page" :width="chunkColumns.columnWidth('page')" align="center" :sortable="{ sortDirections: ['ascend', 'descend'] }" :body-cell-class="bodyCellClass">
                <template #cell="{ record }">
                  {{ record.page ?? '—' }}
                </template>
              </a-table-column>

              <a-table-column title="类型" data-index="source_type" :width="chunkColumns.columnWidth('source_type')" align="center" :body-cell-class="bodyCellClass">
                <template #cell="{ record }">
                  <a-tag :color="sourceTypeColor(record.source_type)" size="small">
                    {{ sourceTypeLabel(record.source_type) }}
                  </a-tag>
                </template>
              </a-table-column>

              <a-table-column title="长度" data-index="content_length" :width="chunkColumns.columnWidth('content_length')" align="center" :sortable="{ sortDirections: ['ascend', 'descend'] }" :body-cell-class="bodyCellClass" />

              <a-table-column title="内容预览" data-index="content" :width="chunkColumns.columnWidth('content')" :body-cell-class="bodyCellClass">
                <template #cell="{ record }">
                  <div class="content-preview">
                    <p>{{ preview(record.content) }}</p>
                    <button type="button" @click.stop="toggleExpand(record.chunk_key)">
                      {{ expandedKeys.has(record.chunk_key) ? '收起' : '展开' }}
                    </button>
                  </div>
                  <div v-if="expandedKeys.has(record.chunk_key)" class="expanded-content">
                    <button class="copy-button" type="button" @click.stop="copyContent(record.content)">
                      复制
                    </button>
                    <pre>{{ record.content }}</pre>
                  </div>
                </template>
              </a-table-column>

              <a-table-column title="图片" data-index="image_paths" :width="chunkColumns.columnWidth('image_paths')" align="center" :body-cell-class="bodyCellClass">
                <template #cell="{ record }">
                  <a-badge v-if="record.image_paths?.length" :count="record.image_paths.length" />
                  <span v-else>—</span>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </section>

        <!-- 相关文档 -->
        <section v-if="related.length" class="detail-card related-section">
          <h3>同主体文档 · {{ relatedEntity }}</h3>
          <div
            v-for="doc in related"
            :key="doc.document_id"
            class="related-item"
            @click="router.push('/documents/' + doc.document_id)"
          >
            <span class="related-name">{{ doc.filename }}</span>
            <span class="related-meta">{{ doc.chunk_count }} chunks</span>
            <span class="related-meta">{{ formatTime(doc.updated_at) }}</span>
          </div>
        </section>
      </template>

      <a-empty v-else-if="!loading" description="文档不存在" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { IconFile, IconLeft } from '@arco-design/web-vue/es/icon'
import type { TableData } from '@arco-design/web-vue/es/table/interface'
import type { Document, DocumentChunk, DocumentChunksSource } from '../../api/documents'
import { getDocumentChunks, getRelatedDocuments } from '../../api/documents'
import { ERROR_HINTS } from '../../utils/errorHints'
import { sourceTypeLabel } from '../../utils/labelMaps'
import { useResizableColumns } from '../../composables/useResizableColumns'

const route = useRoute()
const router = useRouter()

const document = ref<Document | null>(null)
const chunks = ref<DocumentChunk[]>([])
const chunksSource = ref<DocumentChunksSource>('none')
const loading = ref(false)
const keyword = ref('')
const expandedKeys = ref<Set<string>>(new Set())
const PAGE_SIZE = 20
const currentPage = ref(1)
const highlightChunkId = ref<string | null>(null)
const highlightChunkKey = ref<string | null>(null)
const related = ref<Document[]>([])
const relatedEntity = ref('')
const chunkColumns = useResizableColumns('enterprise-rag:document-chunks:v2', {
  sequence: 56,
  section_title: 260,
  page: 86,
  source_type: 92,
  content_length: 86,
  content: undefined,
  image_paths: 64,
})

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  uploaded: { label: '已上传', color: 'arcoblue' },
  processing: { label: '处理中', color: 'orange' },
  parsing: { label: '解析中', color: 'orange' },
  reading: { label: '读取中', color: 'orange' },
  normalizing: { label: '标准化', color: 'orange' },
  chunking: { label: '切片中', color: 'orange' },
  embedding: { label: '向量化', color: 'orange' },
  saving: { label: '写入中', color: 'orange' },
  completed: { label: '已完成', color: 'green' },
  failed: { label: '失败', color: 'red' },
}

const chunkSourceLabel = computed(() => {
  if (chunksSource.value === 'milvus') return '已入库'
  if (chunksSource.value === 'parsed_artifact') return '仅解析产物'
  return '暂无切片'
})

const chunkSourceColor = computed(() => {
  if (chunksSource.value === 'milvus') return 'green'
  if (chunksSource.value === 'parsed_artifact') return 'orange'
  return 'gray'
})

const errorHint = computed(() => {
  const code = document.value?.error_code
  return code ? ERROR_HINTS[code] : ''
})

const filteredChunks = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return chunks.value
  return chunks.value.filter((chunk) => {
    const fields = [
      chunk.content,
      chunk.section_title,
      chunk.title,
      chunk.table_title ?? '',
      chunk.source_type,
    ]
    return fields.some((field) => field.toLowerCase().includes(q))
  })
})

function statusLabel(status: string) {
  return STATUS_MAP[status]?.label ?? status
}

function statusColor(status: string) {
  return STATUS_MAP[status]?.color ?? 'gray'
}

function sourceTypeColor(sourceType: string) {
  return sourceType.startsWith('table_') ? 'orange' : 'arcoblue'
}

function formatTime(value: string) {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 19)
}

function preview(content: string) {
  if (content.length <= 200) return content
  return `${content.slice(0, 200)}...`
}

function toggleExpand(key: string) {
  const next = new Set(expandedKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedKeys.value = next
}

async function copyContent(content: string) {
  try {
    await navigator.clipboard.writeText(content)
  } catch {
    // clipboard API unavailable (e.g. non-HTTPS)
  }
}

function goBack() {
  router.push('/documents')
}

async function loadDetail() {
  const documentId = String(route.params.documentId || '')
  if (!documentId) return
  loading.value = true
  try {
    const payload = await getDocumentChunks(documentId)
    document.value = payload.document
    chunks.value = payload.chunks
    chunksSource.value = payload.chunks_source
    // 数据加载后尝试高亮
    applyHighlight()

    // 加载相关文档
    try {
      const rel = await getRelatedDocuments(documentId)
      related.value = rel.related
      relatedEntity.value = rel.entity
    } catch {
      related.value = []
      relatedEntity.value = ''
    }
  } catch {
    // 404 or other errors — empty state will show
  } finally {
    loading.value = false
  }
}

function onPageChange(page: number) {
  currentPage.value = page
}

function rowClass(record: DocumentChunk) {
  if (isHighlightedChunk(record)) {
    return 'chunk-row-highlight'
  }
  return ''
}

function bodyCellClass(record: TableData) {
  if (isHighlightedChunkKey(record.chunk_key)) {
    return 'chunk-cell-highlight'
  }
  return ''
}

function isHighlightedChunk(record: DocumentChunk) {
  return isHighlightedChunkKey(record.chunk_key)
}

function isHighlightedChunkKey(chunkKey: unknown) {
  return highlightChunkKey.value != null && String(chunkKey || '') === highlightChunkKey.value
}

function applyHighlight() {
  const rawKey = route.query.highlight_chunk_key
  const rawLegacyId = route.query.highlight_chunk
  const requestedKey = typeof rawKey === 'string' ? rawKey : ''
  const requestedLegacyId = typeof rawLegacyId === 'string' ? rawLegacyId : ''
  if (!requestedKey && !requestedLegacyId) {
    highlightChunkId.value = null
    highlightChunkKey.value = null
    return
  }
  highlightChunkId.value = requestedLegacyId || requestedKey
  highlightChunkKey.value = null
  // 确保 keyword 不干扰高亮 chunk 的可见性
  keyword.value = ''

  let index = -1
  if (requestedKey) {
    index = chunks.value.findIndex((c) => c.chunk_key === requestedKey)
  }
  if (index === -1 && requestedLegacyId) {
    index = chunks.value.findIndex(
      (c) => c.milvus_chunk_id != null && String(c.milvus_chunk_id) === requestedLegacyId,
    )
  }
  if (index === -1) {
    Message.warning('未找到对应 chunk，可能索引已重建或链接来自旧记录。')
    return
  }
  highlightChunkKey.value = chunks.value[index].chunk_key
  const targetPage = Math.floor(index / PAGE_SIZE) + 1
  currentPage.value = targetPage
  scrollToHighlightedChunk()
}

function scrollToHighlightedChunk() {
  nextTick(() => {
    window.requestAnimationFrame(() => {
      const row = window.document.querySelector('.chunk-row-highlight') as HTMLElement | null
      const cell = window.document.querySelector('.chunk-cell-highlight') as HTMLElement | null
      const target = row || cell?.closest('tr') || cell
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })
  })
}

// route 变化时重新应用高亮（route.params 不变时组件可能复用）
watch(() => [route.query.highlight_chunk_key, route.query.highlight_chunk], () => {
  if (chunks.value.length > 0) {
    applyHighlight()
  }
})

// 用户手动搜索时重置页码（高亮模式下 keyword 被 applyHighlight 清空时跳过）
watch(keyword, () => {
  if (highlightChunkId.value != null && keyword.value === '') {
    return
  }
  currentPage.value = 1
})

watch(() => route.params.documentId, () => {
  document.value = null
  chunks.value = []
  related.value = []
  relatedEntity.value = ''
  currentPage.value = 1
  keyword.value = ''
  highlightChunkId.value = null
  highlightChunkKey.value = null
  loadDetail()
})

onMounted(loadDetail)
</script>

<style scoped>
.document-detail-page {
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  padding: 0;
}
.back-link:hover {
  color: var(--accent);
}

.detail-spin {
  width: 100%;
}

.detail-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  overflow: hidden;
}
.chunks-card {
  margin-top: 12px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.document-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.document-icon {
  flex: 0 0 auto;
}
.document-title span {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-stack {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.metadata-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.metadata-item {
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: var(--radius-md);
  padding: 8px 10px;
  min-width: 0;
}
.metadata-item span {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
}
.metadata-item strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error-panel {
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid rgba(245, 63, 63, 0.22);
  background: #fff5f5;
  border-radius: var(--radius-md);
  color: var(--error);
  font-size: 12px;
  word-break: break-word;
}
.error-code {
  font-weight: 700;
  margin-right: 8px;
}

.chunks-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}
.chunks-toolbar h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}
.chunks-toolbar p {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.chunk-search {
  width: 260px;
  max-width: 100%;
}

.section-cell {
  display: inline-block;
  max-width: 100%;
  color: var(--text-secondary);
  line-height: 1.45;
  white-space: normal;
  word-break: break-word;
}
.content-preview {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.content-preview p {
  flex: 1;
  min-width: 0;
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}
.content-preview button,
.copy-button {
  flex: 0 0 auto;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 5px 8px;
}
.content-preview button:hover,
.copy-button:hover {
  color: var(--accent);
  border-color: var(--border-accent);
}
.expanded-content {
  position: relative;
  margin-top: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: var(--radius-md);
}
.expanded-content pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.7;
  font-family: var(--font-sans);
}
.copy-button {
  position: absolute;
  top: 8px;
  right: 8px;
}

.related-section {
  margin-top: 12px;
}

.related-section h3 {
  margin: 0 0 10px;
  color: var(--text-primary);
  font-size: 16px;
}

.related-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s;
}
.related-item:hover {
  border-color: var(--border-accent);
}
.related-item + .related-item {
  margin-top: 6px;
}

.related-name {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.related-meta {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

:deep(.chunk-row-highlight .arco-table-td),
:deep(.chunk-cell-highlight) {
  background: #fff7ed !important;
  border-top: 1px solid #fdba74 !important;
  border-bottom: 1px solid #fdba74 !important;
}

:deep(.chunk-row-highlight .arco-table-td:first-child),
:deep(.chunk-cell-highlight:first-child) {
  box-shadow: inset 3px 0 0 #f97316;
}

@media (max-width: 1100px) {
  .metadata-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .detail-header,
  .chunks-toolbar {
    flex-direction: column;
  }

  .metadata-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chunk-search {
    width: 100%;
  }
}
</style>
