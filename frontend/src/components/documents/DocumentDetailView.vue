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
              <div>
                <h3>{{ document.filename }}</h3>
                <p>文档主体：{{ document.entity_name || '—' }}</p>
              </div>
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
              <p>共 {{ filteredChunks.length }} / {{ chunks.length }} 个 chunks</p>
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
            :pagination="{ pageSize: 20 }"
            :bordered="false"
            row-key="chunk_key"
            class="chunk-table"
          >
            <template #columns>
              <a-table-column title="#" :width="56" align="center">
                <template #cell="{ record }">
                  {{ record.sequence }}
                </template>
              </a-table-column>

              <a-table-column title="章节" data-index="section_title" :width="190">
                <template #cell="{ record }">
                  <span class="section-cell" :title="record.section_title || record.title">
                    {{ record.section_title || record.title || '—' }}
                  </span>
                </template>
              </a-table-column>

              <a-table-column title="页码" data-index="page" :width="70" align="center" :sortable="{ sortDirections: ['ascend', 'descend'] }">
                <template #cell="{ record }">
                  {{ record.page ?? '—' }}
                </template>
              </a-table-column>

              <a-table-column title="类型" data-index="source_type" :width="110" align="center">
                <template #cell="{ record }">
                  <a-tag :color="sourceTypeColor(record.source_type)" size="small">
                    {{ sourceTypeLabel(record.source_type) }}
                  </a-tag>
                </template>
              </a-table-column>

              <a-table-column title="长度" data-index="content_length" :width="82" align="center" :sortable="{ sortDirections: ['ascend', 'descend'] }" />

              <a-table-column title="内容预览" data-index="content">
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

              <a-table-column title="图片" data-index="image_paths" :width="70" align="center">
                <template #cell="{ record }">
                  <a-badge v-if="record.image_paths?.length" :count="record.image_paths.length" />
                  <span v-else>—</span>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </section>
      </template>

      <a-empty v-else-if="!loading" description="文档不存在" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { IconFile, IconLeft } from '@arco-design/web-vue/es/icon'
import type { Document, DocumentChunk, DocumentChunksSource } from '../../api/documents'
import { getDocumentChunks } from '../../api/documents'
import { ERROR_HINTS } from '../../utils/errorHints'

const route = useRoute()
const router = useRouter()

const document = ref<Document | null>(null)
const chunks = ref<DocumentChunk[]>([])
const chunksSource = ref<DocumentChunksSource>('none')
const loading = ref(false)
const keyword = ref('')
const expandedKeys = ref<Set<string>>(new Set())

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

function sourceTypeLabel(sourceType: string) {
  const map: Record<string, string> = {
    text: '文本',
    table_summary: '表格摘要',
    table_full: '完整表格',
    table_row_group: '表格行组',
  }
  return map[sourceType] ?? sourceType
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
  } catch {
    // 404 or other errors — empty state will show
  } finally {
    loading.value = false
  }
}

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
  margin-bottom: 14px;
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
  padding: 20px;
  overflow: hidden;
}
.chunks-card {
  margin-top: 16px;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border);
}
.document-title {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}
.document-icon {
  flex: 0 0 auto;
  margin-top: 4px;
}
.document-title h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
  line-height: 1.35;
  word-break: break-word;
}
.document-title p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 13px;
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
  gap: 10px;
  margin-top: 16px;
}
.metadata-item {
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  min-width: 0;
}
.metadata-item span {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
}
.metadata-item strong {
  display: block;
  margin-top: 6px;
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
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.chunks-toolbar h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}
.chunks-toolbar p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.chunk-search {
  width: 280px;
  max-width: 100%;
}

.section-cell {
  display: inline-block;
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
