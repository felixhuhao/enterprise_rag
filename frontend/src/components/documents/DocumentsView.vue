<!--
  文档管理页

  上传 PDF/MD、查看状态、处理入库、删除
-->
<template>
  <div class="documents-page">
    <div class="documents-card">
      <div class="documents-header">
        <h3>文档管理</h3>
        <p class="documents-desc">上传 PDF 或 Markdown 文档，解析后写入向量知识库</p>
      </div>

      <!-- 上传区域 -->
      <div class="upload-area">
        <a-upload
          :auto-upload="false"
          :show-file-list="false"
          accept=".pdf,.md,.markdown"
          @change="onFileSelect"
        >
          <template #upload-button>
            <a-button type="primary" :loading="uploading">
              <template #icon><icon-upload /></template>
              上传文件
            </a-button>
          </template>
        </a-upload>
        <span class="upload-hint">支持 .pdf .md .markdown</span>
      </div>

      <!-- 文档列表 -->
      <a-table
        :data="docs"
        :pagination="{ pageSize: 20 }"
        :bordered="false"
        row-key="document_id"
        class="doc-table"
      >
        <template #columns>
          <a-table-column title="文件名" data-index="filename" :width="240">
            <template #cell="{ record }">
              <span class="doc-name">
                <icon-file v-if="record.file_type === 'pdf'" style="color: var(--error)" />
                <icon-file v-else style="color: var(--accent)" />
                {{ record.filename }}
              </span>
            </template>
          </a-table-column>

          <a-table-column title="状态" data-index="status" :width="140" align="center">
            <template #cell="{ record }">
              <a-tag :color="statusColor(record.status)" size="small">
                {{ statusLabel(record.status) }}
              </a-tag>
            </template>
          </a-table-column>

          <a-table-column title="Chunks" data-index="chunk_count" :width="80" align="center" />
          <a-table-column title="图片" data-index="image_count" :width="70" align="center" />

          <a-table-column title="上传时间" data-index="created_at" :width="180">
            <template #cell="{ record }">
              {{ formatTime(record.created_at) }}
            </template>
          </a-table-column>

          <a-table-column title="操作" :width="200" align="center">
            <template #cell="{ record }">
              <a-space>
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
          <div class="error-msg">{{ doc.error_msg }}</div>
        </a-collapse-item>
      </a-collapse>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  IconUpload,
  IconFile,
} from '@arco-design/web-vue/es/icon'
import type { Document } from '../../api/documents'
import {
  listDocuments,
  uploadDocument,
  processDocument,
  retryDocument,
  deleteDocument,
  getDocument,
} from '../../api/documents'

const docs = ref<Document[]>([])
const uploading = ref(false)
const pollingIds = ref<Map<string, number>>(new Map())

const failedDocs = computed(() => docs.value.filter((d) => d.status === 'failed'))

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
    const busy = ['processing', 'parsing', 'reading', 'normalizing', 'chunking', 'embedding', 'saving'].includes(doc.status)
    if (busy && !pollingIds.value.has(doc.document_id)) {
      const id = window.setInterval(() => pollDoc(doc.document_id), 3000)
      pollingIds.value.set(doc.document_id, id)
    }
  }
}

async function pollDoc(docId: string) {
  try {
    const updated = await getDocument(docId)
    const idx = docs.value.findIndex((d) => d.document_id === docId)
    if (idx >= 0) docs.value[idx] = updated
    const busy = ['processing', 'parsing', 'reading', 'normalizing', 'chunking', 'embedding', 'saving'].includes(updated.status)
    if (!busy) {
      const tid = pollingIds.value.get(docId)
      if (tid) {
        clearInterval(tid)
        pollingIds.value.delete(docId)
      }
    }
  } catch {
    // ignore polling errors
  }
}

async function onFileSelect(fileList: File[]) {
  const file = fileList[0]?.file
  if (!file) return
  uploading.value = true
  try {
    await uploadDocument(file)
    await refresh()
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '上传失败')
  } finally {
    uploading.value = false
  }
}

async function handleProcess(docId: string) {
  try {
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
    await deleteDocument(docId)
    docs.value = docs.value.filter((d) => d.document_id !== docId)
  } catch (e: any) {
    window.alert(e?.response?.data?.detail ?? '删除失败')
  }
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.documents-page {
  max-width: 960px;
  margin: 0 auto;
  animation: fadeIn 0.3s var(--ease-out);
}

.documents-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 28px;
}

.documents-header {
  margin-bottom: 20px;
}
.documents-header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.documents-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.upload-area {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.upload-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.doc-table {
  margin-bottom: 16px;
}
.doc-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.error-collapse {
  margin-top: 12px;
}
.error-msg {
  font-size: 12px;
  color: var(--error, #f53f3f);
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
