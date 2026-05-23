<!--
  文档管理页

  上传 PDF/MD、查看状态、处理入库、删除
-->
<template>
  <div class="documents-page">
    <div class="documents-card">
      <div class="documents-header">
        <div>
          <h3>文档管理</h3>
          <p class="documents-desc">上传 PDF 或 Markdown 文档，解析后写入向量知识库</p>
        </div>
      </div>

      <div class="summary-row">
        <button
          v-for="item in summaryItems"
          :key="item.key"
          class="summary-item"
          :class="{ active: statusFilter === item.key }"
          type="button"
          @click="statusFilter = item.key"
        >
          <span class="summary-value">{{ item.value }}</span>
          <span class="summary-label">{{ item.label }}</span>
        </button>
      </div>

      <!-- 上传区域 -->
      <div class="upload-area">
        <a-upload
          ref="uploadRef"
          :auto-upload="false"
          :show-file-list="false"
          accept=".pdf,.md,.markdown,.zip"
          @change="onFileSelect"
        >
          <template #upload-button>
            <a-button type="primary" :disabled="uploading">
              <template #icon><icon-upload /></template>
              选择文件
            </a-button>
          </template>
        </a-upload>
        <span class="upload-hint">支持 .pdf .md .markdown .zip</span>
      </div>

      <!-- 文件预览 + entity 编辑 -->
      <div v-if="pendingFile" class="upload-preview">
        <div class="preview-file">
          <icon-file style="color: var(--accent)" />
          <span class="preview-filename">{{ pendingFile.name }}</span>
        </div>
        <div class="preview-entity">
          <span class="preview-label">文档主体</span>
          <a-input
            v-model="pendingEntityName"
            placeholder="可选：填写文档所属主体"
            size="small"
            allow-clear
            class="entity-input"
          />
        </div>
        <div class="preview-actions">
          <a-button type="primary" size="small" :loading="uploading" @click="confirmUpload">
            确认上传
          </a-button>
          <a-button size="small" @click="cancelPending">取消</a-button>
        </div>
      </div>

      <!-- 文档列表 -->
      <a-table
        :data="filteredDocs"
        :pagination="{ pageSize: 20 }"
        :bordered="false"
        row-key="document_id"
        class="doc-table"
      >
        <template #columns>
          <a-table-column title="文件名" data-index="filename">
            <template #cell="{ record }">
              <span class="doc-name">
                <icon-file class="doc-icon" :style="{ color: record.file_type === 'pdf' ? 'var(--error)' : 'var(--accent)' }" />
                <span class="doc-filename" :title="record.filename">{{ record.filename }}</span>
              </span>
            </template>
          </a-table-column>

          <a-table-column title="状态" data-index="status" :width="100" align="center">
            <template #cell="{ record }">
              <a-tag v-if="record.cleanup_status === 'milvus_delete_failed'" color="orangered" size="small">
                待清理
              </a-tag>
              <a-tag v-else :color="statusColor(record.status)" size="small">
                {{ statusLabel(record.status) }}
              </a-tag>
            </template>
          </a-table-column>

          <a-table-column title="文档主体" data-index="entity_name" :width="180">
            <template #cell="{ record }">
              <a-input
                v-if="record.status === 'uploaded' && record.cleanup_status !== 'milvus_delete_failed'"
                v-model="record.entity_name"
                placeholder="可选：填写文档所属主体"
                size="mini"
                allow-clear
                @blur="handleEntityBlur(record)"
              />
              <span v-else class="entity-text">{{ record.entity_name || '—' }}</span>
            </template>
          </a-table-column>

          <a-table-column title="Chunks" data-index="chunk_count" :width="80" align="center" />
          <a-table-column title="图片" data-index="image_count" :width="70" align="center" />

          <a-table-column title="上传时间" data-index="created_at" :width="180">
            <template #cell="{ record }">
              {{ formatTime(record.created_at) }}
            </template>
          </a-table-column>

          <a-table-column title="操作" :width="180" align="center">
            <template #cell="{ record }">
              <a-space>
                <!-- cleanup_status 优先：待清理状态只显示修复删除 -->
                <template v-if="record.cleanup_status === 'milvus_delete_failed'">
                  <a-popconfirm content="确认重试清理向量数据并删除记录？" @ok="handleRepairDelete(record.document_id)">
                    <a-button type="primary" size="small" status="warning">修复删除</a-button>
                  </a-popconfirm>
                </template>
                <template v-else>
                  <a-button
                    v-if="record.status === 'uploaded'"
                    type="primary"
                    size="small"
                    @click="handleProcess(record.document_id)"
                  >
                    处理入库
                  </a-button>
                  <a-button
                    v-if="record.status === 'failed'"
                    status="danger"
                    size="small"
                    @click="handleRetry(record.document_id)"
                  >
                    重试
                  </a-button>
                  <a-popconfirm content="确认删除该文档及其向量数据？" @ok="handleDelete(record.document_id)">
                    <a-button size="small" status="danger">删除</a-button>
                  </a-popconfirm>
                </template>
              </a-space>
            </template>
          </a-table-column>
        </template>
      </a-table>

      <!-- 错误信息展示 -->
      <a-collapse v-if="failedDocs.length" :default-active-key="[]" class="error-collapse">
        <a-collapse-item
          v-for="doc in failedDocs"
          :key="doc.document_id"
          :header="`${doc.filename} — 失败原因`"
        >
          <div class="error-msg">
            <span v-if="doc.error_code" class="error-code">{{ doc.error_code }}</span>
            <span v-if="errorHint(doc)">{{ errorHint(doc) }}</span>
            <span v-else>{{ doc.error_msg }}</span>
          </div>
        </a-collapse-item>
      </a-collapse>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  IconUpload,
  IconFile,
} from '@arco-design/web-vue/es/icon'
import type { FileItem } from '@arco-design/web-vue'
import type { Document } from '../../api/documents'
import { ERROR_HINTS } from '../../utils/errorHints'
import {
  listDocuments,
  uploadDocument,
  processDocument,
  retryDocument,
  deleteDocument,
  repairDeleteDocument,
  getDocument,
  suggestMetadata,
  updateDocumentEntity,
} from '../../api/documents'

const docs = ref<Document[]>([])
const uploading = ref(false)
const pendingFile = ref<File | null>(null)
const pendingEntityName = ref('')
const pollingIds = ref<Map<string, number>>(new Map())
const uploadRef = ref<any>(null)
const statusFilter = ref('all')

const BUSY_STATUSES = ['processing', 'parsing', 'reading', 'normalizing', 'chunking', 'embedding', 'saving']

const failedDocs = computed(() => docs.value.filter((d) => d.status === 'failed'))
const pendingCleanupDocs = computed(() => docs.value.filter((d) => d.cleanup_status === 'milvus_delete_failed'))
const processingDocs = computed(() => docs.value.filter((d) => BUSY_STATUSES.includes(d.status)))
const completedDocs = computed(() => docs.value.filter((d) => d.status === 'completed'))

const summaryItems = computed(() => [
  { key: 'all', label: '全部', value: docs.value.length },
  { key: 'completed', label: '已完成', value: completedDocs.value.length },
  { key: 'processing', label: '处理中', value: processingDocs.value.length },
  { key: 'failed', label: '失败', value: failedDocs.value.length },
  { key: 'cleanup', label: '待清理', value: pendingCleanupDocs.value.length },
])

const filteredDocs = computed(() => {
  if (statusFilter.value === 'completed') return completedDocs.value
  if (statusFilter.value === 'processing') return processingDocs.value
  if (statusFilter.value === 'failed') return failedDocs.value
  if (statusFilter.value === 'cleanup') return pendingCleanupDocs.value
  return docs.value
})

function errorHint(doc: Document): string | undefined {
  return doc.error_code ? ERROR_HINTS[doc.error_code] : undefined
}

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

function statusLabel(s: string) {
  return STATUS_MAP[s]?.label ?? s
}
function statusColor(s: string) {
  return STATUS_MAP[s]?.color ?? 'gray'
}
function formatTime(t: string) {
  if (!t) return ''
  return t.replace('T', ' ').slice(0, 19)
}

async function refresh() {
  docs.value = await listDocuments()
  startPolling()
}

function startPolling() {
  for (const doc of docs.value) {
    const busy = BUSY_STATUSES.includes(doc.status)
    if (busy && !pollingIds.value.has(doc.document_id)) {
      const id = window.setInterval(() => pollDoc(doc.document_id), 3000)
      pollingIds.value.set(doc.document_id, id)
    }
  }
}

function stopPolling(docId: string) {
  const tid = pollingIds.value.get(docId)
  if (tid) {
    clearInterval(tid)
    pollingIds.value.delete(docId)
  }
}

/** 连续轮询失败计数 */
const pollFailCount = ref<Record<string, number>>({})

async function pollDoc(docId: string) {
  try {
    const updated = await getDocument(docId)
    // 成功则重置失败计数
    pollFailCount.value[docId] = 0
    const idx = docs.value.findIndex((d) => d.document_id === docId)
    if (idx >= 0) docs.value[idx] = updated
    const busy = BUSY_STATUSES.includes(updated.status)
    if (!busy) {
      stopPolling(docId)
    }
  } catch {
    const count = (pollFailCount.value[docId] || 0) + 1
    pollFailCount.value[docId] = count
    // 连续失败 3 次或 404 等错误，停止轮询
    if (count >= 3) {
      stopPolling(docId)
    }
  }
}

function clearAllPolling() {
  for (const tid of pollingIds.value.values()) {
    clearInterval(tid)
  }
  pollingIds.value.clear()
}

async function onFileSelect(fileList: FileItem[]) {
  const lastItem = fileList[fileList.length - 1]
  const rawFile = lastItem?.file
  if (!rawFile) return
  pendingFile.value = rawFile
  try {
    const { suggested_entity_name } = await suggestMetadata(rawFile.name)
    pendingEntityName.value = suggested_entity_name
  } catch {
    pendingEntityName.value = ''
  }
}

function cancelPending() {
  pendingFile.value = null
  pendingEntityName.value = ''
}

async function confirmUpload() {
  if (!pendingFile.value) return
  uploading.value = true
  try {
    await uploadDocument(pendingFile.value, pendingEntityName.value)
    pendingFile.value = null
    pendingEntityName.value = ''
    // 清除 a-upload 内部累积的文件列表
    try { uploadRef.value?.clearFiles?.() } catch { /* ignore */ }
    await refresh()
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '上传失败')
  } finally {
    uploading.value = false
  }
}

function handleEntityBlur(record: Document) {
  updateDocumentEntity(record.document_id, record.entity_name).catch((e: any) => {
    window.alert(e?.response?.data?.detail ?? '更新失败')
  })
}

async function handleProcess(docId: string) {
  try {
    const doc = docs.value.find((d) => d.document_id === docId)
    if (doc) await updateDocumentEntity(docId, doc.entity_name)
    await processDocument(docId)
    await refresh()
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '启动处理失败')
  }
}

async function handleRetry(docId: string) {
  try {
    await retryDocument(docId)
    await refresh()
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '重试失败')
  }
}

async function handleDelete(docId: string) {
  try {
    const res = await deleteDocument(docId)
    stopPolling(docId)
    if (res.status === 'partial') {
      // Milvus 清理失败，更新记录而非移除
      const updated = docs.value.find((d) => d.document_id === docId)
      if (updated) {
        updated.cleanup_status = 'milvus_delete_failed'
      }
      window.alert('向量数据清理未完成，文档已标记为"待清理"，可稍后点击"修复删除"')
    } else {
      docs.value = docs.value.filter((d) => d.document_id !== docId)
    }
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '删除失败')
  }
}

async function handleRepairDelete(docId: string) {
  try {
    await repairDeleteDocument(docId)
    stopPolling(docId)
    docs.value = docs.value.filter((d) => d.document_id !== docId)
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '修复删除失败')
  }
}

onMounted(() => {
  refresh()
})

onUnmounted(() => {
  clearAllPolling()
})
</script>

<style scoped>
.documents-page {
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.documents-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  overflow: hidden;
}

.documents-header {
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.documents-header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}
.documents-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.summary-row {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.summary-item {
  text-align: left;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.15s var(--ease-out), background 0.15s var(--ease-out);
}
.summary-item:hover,
.summary-item.active {
  border-color: var(--border-accent);
  background: var(--accent-subtle);
}
.summary-value {
  display: block;
  font-size: 20px;
  line-height: 1;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.summary-label {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.upload-area {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #f8fafc;
}
.upload-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.upload-preview {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  margin-bottom: 20px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: var(--radius-md, 8px);
}
.preview-file {
  display: flex;
  align-items: center;
  gap: 6px;
}
.preview-filename {
  font-size: 13px;
  color: var(--text-primary);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.preview-entity {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}
.preview-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}
.entity-input {
  flex: 1;
  min-width: 160px;
}
.preview-actions {
  display: flex;
  gap: 8px;
}
.entity-text {
  font-size: 12px;
  color: var(--text-secondary);
}

.doc-table {
  margin-bottom: 16px;
}
.doc-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  max-width: 520px;
  min-width: 0;
}
.doc-icon {
  flex: 0 0 auto;
}
.doc-filename {
  display: inline-block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.error-collapse {
  margin-top: 12px;
}
.error-msg {
  font-size: 12px;
  color: var(--error, #f53f3f);
  white-space: pre-wrap;
  word-break: break-all;
}
.error-code {
  font-family: var(--font-display);
  font-weight: 600;
  margin-right: 8px;
}

@media (max-width: 980px) {
  .summary-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .upload-preview {
    align-items: stretch;
    flex-direction: column;
  }

  .preview-actions {
    justify-content: flex-end;
  }
}
</style>
