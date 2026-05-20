<!--
  知识库管理页

  文档列表 + 上传 PDF + 一键处理（OCR → Markdown → Milvus 入库）+ 删除
-->
<template>
  <div class="knowledge-page">
    <!-- 顶部操作栏 -->
    <div class="page-header">
      <div>
        <h3>知识库管理</h3>
        <p class="page-desc">上传 PDF 文档，OCR 解析后入库供 AI 检索</p>
      </div>
      <a-upload
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf"
        @change="onFileSelect"
      >
        <template #upload-button>
          <a-button type="primary" :loading="store.uploading">
            <template #icon><icon-upload /></template>
            上传 PDF
          </a-button>
        </template>
      </a-upload>
    </div>

    <!-- 文档列表 -->
    <a-table
      :data="store.documents"
      :loading="store.loading"
      :pagination="{ pageSize: 10 }"
      row-key="id"
    >
      <template #columns>
        <a-table-column title="文件名" data-index="filename" :width="240" />
        <a-table-column title="状态" :width="120">
          <template #cell="{ record }">
            <span :class="['status-dot', record.status]"></span>
            {{ statusLabel(record.status) }}
          </template>
        </a-table-column>
        <a-table-column title="文档片段" data-index="doc_count" :width="100" />
        <a-table-column title="含图文档" data-index="image_count" :width="100" />
        <a-table-column title="上传时间" data-index="created_at" :width="180" />
        <a-table-column title="操作" :width="220">
          <template #cell="{ record }">
            <a-space>
              <a-button
                v-if="record.status === 'uploaded' || record.status === 'failed'"
                type="primary"
                size="small"
                @click="store.process(record.id)"
              >
                处理入库
              </a-button>
              <a-popconfirm content="确认删除？将从知识库中移除。" @ok="store.remove(record.id)">
                <a-button status="danger" size="small">删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </a-table-column>
      </template>
      <template #empty>
        <a-empty description="暂无文档，上传 PDF 开始" />
      </template>
    </a-table>

    <!-- 错误提示 -->
    <div
      v-for="doc in store.documents.filter((d: any) => d.status === 'failed')"
      :key="'err-' + doc.id"
      class="error-alert"
    >
      <div class="error-title">{{ doc.filename }} 处理失败</div>
      <div class="error-msg">{{ doc.error_msg }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { IconUpload } from '@arco-design/web-vue/es/icon'
import { useKnowledgeStore } from '../../stores/knowledge'

const store = useKnowledgeStore()

onMounted(() => {
  store.fetchDocuments()
})

function onFileSelect(fileItem: any) {
  const file = fileItem.file?.file || fileItem
  if (!(file instanceof File)) return
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    window.alert('仅支持 PDF 文件')
    return
  }
  store.upload(file)
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '已解析',
    saving: '入库中',
    completed: '已完成',
    failed: '失败',
  }
  return map[status] || status
}
</script>

<style scoped>
.knowledge-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.3s var(--ease-out);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.page-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

/* Status dot */
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.status-dot.uploaded { background: var(--info); }
.status-dot.parsing  { background: var(--warning); animation: glowPulse 1.5s ease-in-out infinite; }
.status-dot.parsed   { background: var(--info); }
.status-dot.saving   { background: var(--warning); animation: glowPulse 1.5s ease-in-out infinite; }
.status-dot.completed { background: var(--success); }
.status-dot.failed   { background: var(--danger); }

@keyframes glowPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; box-shadow: 0 0 6px currentColor; }
}

/* Error alerts */
.error-alert {
  margin-top: 12px;
  padding: 10px 16px;
  background: rgba(240, 96, 96, 0.06);
  border: 1px solid rgba(240, 96, 96, 0.15);
  border-radius: var(--radius-sm);
}
.error-title {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--danger);
  font-size: 13px;
}
.error-msg {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}
</style>
