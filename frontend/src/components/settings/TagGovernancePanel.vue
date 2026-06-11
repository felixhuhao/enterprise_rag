<template>
  <div>
    <div v-if="!isAdmin" class="readonly-note">当前用户没有修改权限。</div>
    <div class="strategy-note">
      结构化标签由后端内置规则产生；这里只能覆盖显示文案和开关，不能新增或删除标签。关闭标签会影响后续入库结果，已有索引需要重建后完全一致。
    </div>

    <a-spin :loading="tagMetricsLoading" style="width: 100%">
      <div class="tag-metric-grid">
        <div class="tag-metric-card">
          <span>文档数</span>
          <strong>{{ tagMetrics?.summary.document_count ?? 0 }}</strong>
        </div>
        <div class="tag-metric-card">
          <span>切片数</span>
          <strong>{{ tagMetrics?.summary.chunk_count ?? 0 }}</strong>
        </div>
        <div class="tag-metric-card">
          <span>无标签切片</span>
          <strong>{{ tagMetrics?.summary.zero_tag_chunks ?? 0 }}</strong>
        </div>
        <div class="tag-metric-card">
          <span>关键词超限</span>
          <strong>{{ tagMetrics?.summary.too_many_keywords_chunks ?? 0 }}</strong>
        </div>
      </div>
    </a-spin>

    <details class="tag-preview-box">
      <summary>
        <span>规则预览</span>
        <small>粘贴文本或选择文档，只运行规则，不写入存储。</small>
      </summary>
      <div class="tag-preview-controls">
        <label>
          <span>选择文档</span>
          <a-select
            v-model="previewDocument"
            placeholder="可选，选择后预览该文档切片"
            allow-clear
            :loading="previewDocsLoading"
          >
            <a-option v-for="doc in previewDocuments" :key="doc.document_id" :value="doc.document_id">
              {{ doc.filename }}
            </a-option>
          </a-select>
        </label>
        <label>
          <span>章节标题</span>
          <a-input v-model="previewSection" placeholder="可选，粘贴文本时用于模拟 section_title" allow-clear />
        </label>
      </div>
      <label class="tag-preview-text">
        <span>预览文本</span>
        <a-textarea
          v-model="previewBody"
          placeholder="粘贴一段制度内容；未选择文档时必填"
          :auto-size="{ minRows: 3, maxRows: 6 }"
        />
      </label>
      <div class="tag-preview-actions">
        <a-button type="primary" :loading="previewLoading" @click="$emit('runPreview')">运行预览</a-button>
        <a-button @click="$emit('clearPreview')">清空</a-button>
      </div>
      <div v-if="previewResult" class="tag-preview-result">
        <div class="tag-preview-summary">
          <span>{{ previewResult.summary.matched_chunks }} / {{ previewResult.summary.chunk_count }} 个切片命中标签</span>
          <span>{{ previewResult.summary.tag_count }} 个标签</span>
        </div>
        <div v-if="previewResult.tag_counts.length" class="tag-preview-tags">
          <a-tag v-for="tag in previewResult.tag_counts" :key="tag.tag_key" size="small" color="green">
            {{ tag.label }} {{ tag.chunks }}
          </a-tag>
        </div>
        <div class="preview-items">
          <article v-for="item in previewItems" :key="item.chunk_key || item.search_text_preview" class="preview-item">
            <div class="preview-item-head">
              <strong>{{ item.section_title || item.source_type }}</strong>
              <small>{{ item.search_text_length }} chars</small>
            </div>
            <div class="tag-preview-tags">
              <a-tag v-for="tag in item.structured_tags" :key="tag.tag_key" size="small" color="green">
                {{ tag.label }}
              </a-tag>
              <span v-if="!item.structured_tags.length" class="muted">无标签</span>
            </div>
            <p v-if="item.evidence.length">{{ item.evidence[0].snippet }}</p>
            <small v-if="item.keywords.length">关键词：{{ item.keywords.join(' / ') }}</small>
          </article>
          <div v-if="hiddenPreviewItemCount" class="preview-more">
            仅展示前 {{ previewItems.length }} 条，另有 {{ hiddenPreviewItemCount }} 条未展示。
          </div>
        </div>
      </div>
    </details>

    <a-spin :loading="tagLoading" style="width: 100%">
      <div class="tag-table-wrap">
        <a-table :data="tagRecords" row-key="tag_key" size="small" :pagination="false">
          <template #columns>
            <a-table-column title="标签" data-index="label" :width="240">
              <template #cell="{ record }">
                <div class="tag-main">
                  <strong>{{ record.label }}</strong>
                  <code>{{ record.tag_key }}</code>
                </div>
              </template>
            </a-table-column>
            <a-table-column title="说明" data-index="description">
              <template #cell="{ record }">
                <span class="tag-description">{{ record.description }}</span>
              </template>
            </a-table-column>
            <a-table-column title="范围" data-index="profile" :width="150">
              <template #cell="{ record }">
                <div class="tag-status">
                  <a-tag size="small">{{ tagScopeLabel(record.scope) }}</a-tag>
                  <a-tag size="small">{{ tagProfileLabel(record.profile) }}</a-tag>
                </div>
              </template>
            </a-table-column>
            <a-table-column title="状态" data-index="status" :width="150">
              <template #cell="{ record }">
                <div class="tag-status">
                  <a-tag size="small" :color="record.enabled ? 'green' : 'gray'">
                    {{ record.enabled ? '启用' : '停用' }}
                  </a-tag>
                  <a-tag size="small" :color="record.ui_visible ? 'arcoblue' : 'gray'">
                    {{ record.ui_visible ? '显示' : '隐藏' }}
                  </a-tag>
                </div>
              </template>
            </a-table-column>
            <a-table-column title="优先级" data-index="priority" :width="82" align="center" />
            <a-table-column title="命中数" data-index="count" :width="88" align="center">
              <template #cell="{ record }">
                <div class="tag-count-cell">
                  <strong>{{ tagMetricMap[record.tag_key]?.chunks ?? 0 }}</strong>
                  <small>{{ tagMetricMap[record.tag_key]?.documents ?? 0 }} 文档</small>
                </div>
              </template>
            </a-table-column>
            <a-table-column title="操作" data-index="actions" :width="150" align="right">
              <template #cell="{ record }">
                <div class="row-actions">
                  <a-button size="mini" @click="$emit('openEditor', record)">编辑</a-button>
                  <a-popconfirm content="恢复该标签的内置默认值？" @ok="$emit('resetTag', record)">
                    <a-button size="mini" :disabled="!record.overridden">重置</a-button>
                  </a-popconfirm>
                </div>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
    </a-spin>

    <a-modal :visible="tagEditorOpen" title="编辑标签" :width="620" :footer="false" @update:visible="editorVisible = $event">
      <div class="tag-edit-form">
        <label>
          <span>标签 Key</span>
          <a-input :model-value="selectedTag?.tag_key || ''" disabled />
        </label>
        <label>
          <span>显示名称</span>
          <a-input v-model="tagLabelValue" allow-clear />
        </label>
        <label>
          <span>说明</span>
          <a-textarea v-model="tagDescriptionValue" :auto-size="{ minRows: 3, maxRows: 5 }" />
        </label>
        <div class="tag-toggle-row">
          <a-checkbox v-model="tagEnabledValue">启用标签</a-checkbox>
          <a-checkbox v-model="tagUiVisibleValue">前端显示</a-checkbox>
        </div>
        <div class="modal-actions">
          <a-button @click="editorVisible = false">取消</a-button>
          <a-button type="primary" :loading="tagSaving" @click="$emit('saveEditor')">保存</a-button>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Document } from '../../api/documents'
import type {
  StructuredTagMetrics,
  StructuredTagPreviewResponse,
  StructuredTagRecord,
} from '../../api/structuredTags'

const props = defineProps<{
  isAdmin: boolean
  tagMetricsLoading: boolean
  tagMetrics: StructuredTagMetrics | null
  previewDocsLoading: boolean
  previewLoading: boolean
  previewDocuments: Document[]
  previewDocumentId: string
  previewSectionTitle: string
  previewText: string
  previewResult: StructuredTagPreviewResponse | null
  tagLoading: boolean
  tagRecords: StructuredTagRecord[]
  tagEditorOpen: boolean
  selectedTag: StructuredTagRecord | null
  tagSaving: boolean
  tagLabel: string
  tagDescription: string
  tagEnabled: boolean
  tagUiVisible: boolean
}>()

const emit = defineEmits<{
  (event: 'update:previewDocumentId', value: string): void
  (event: 'update:previewSectionTitle', value: string): void
  (event: 'update:previewText', value: string): void
  (event: 'update:tagEditorOpen', value: boolean): void
  (event: 'update:tagLabel', value: string): void
  (event: 'update:tagDescription', value: string): void
  (event: 'update:tagEnabled', value: boolean): void
  (event: 'update:tagUiVisible', value: boolean): void
  (event: 'runPreview'): void
  (event: 'clearPreview'): void
  (event: 'openEditor', record: StructuredTagRecord): void
  (event: 'resetTag', record: StructuredTagRecord): void
  (event: 'saveEditor'): void
}>()

const previewDocument = computed({
  get: () => props.previewDocumentId,
  set: (value) => emit('update:previewDocumentId', String(value ?? '')),
})

const previewSection = computed({
  get: () => props.previewSectionTitle,
  set: (value) => emit('update:previewSectionTitle', String(value ?? '')),
})

const previewBody = computed({
  get: () => props.previewText,
  set: (value) => emit('update:previewText', String(value ?? '')),
})

const editorVisible = computed({
  get: () => props.tagEditorOpen,
  set: (value) => emit('update:tagEditorOpen', Boolean(value)),
})

const tagLabelValue = computed({
  get: () => props.tagLabel,
  set: (value) => emit('update:tagLabel', String(value ?? '')),
})

const tagDescriptionValue = computed({
  get: () => props.tagDescription,
  set: (value) => emit('update:tagDescription', String(value ?? '')),
})

const tagEnabledValue = computed({
  get: () => props.tagEnabled,
  set: (value) => emit('update:tagEnabled', Boolean(value)),
})

const tagUiVisibleValue = computed({
  get: () => props.tagUiVisible,
  set: (value) => emit('update:tagUiVisible', Boolean(value)),
})

const previewItems = computed(() => props.previewResult?.items.slice(0, 5) ?? [])
const hiddenPreviewItemCount = computed(() => Math.max(0, (props.previewResult?.items.length ?? 0) - previewItems.value.length))
const tagMetricMap = computed(() =>
  Object.fromEntries((props.tagMetrics?.top_tags ?? []).map((row) => [row.tag_key, row])),
)

function tagScopeLabel(scope: string) {
  return scope === 'chunk' ? '切片' : scope
}

function tagProfileLabel(profile: string) {
  return profile === 'enterprise_policy' ? '企业制度' : profile
}
</script>

<style scoped>
.readonly-note {
  margin-bottom: 12px;
  border: 1px solid #fed7aa;
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  color: #7c2d12;
  background: #fff7ed;
  font-size: 12px;
}

.strategy-note {
  margin: 4px 0 10px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.tag-table-wrap {
  min-width: 0;
  overflow-x: hidden;
}

.tag-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.tag-metric-card {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}

.tag-metric-card span,
.tag-count-cell small,
.tag-preview-box summary small,
.preview-item small {
  color: var(--text-muted);
  font-size: 12px;
}

.tag-metric-card strong,
.tag-count-cell strong {
  color: var(--text-primary);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.tag-main {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.tag-main strong {
  color: var(--text-primary);
  font-size: 13px;
}

.tag-main code {
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.tag-description {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.tag-status,
.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.muted {
  color: var(--text-muted);
  font-size: 12px;
}

.tag-count-cell {
  display: grid;
  gap: 1px;
}

.tag-preview-box {
  margin-bottom: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-base);
}

.tag-preview-box summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  list-style: none;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.tag-preview-box summary::-webkit-details-marker {
  display: none;
}

.tag-preview-box summary::after {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
  content: '展开';
}

.tag-preview-box[open] summary::after {
  content: '收起';
}

.tag-preview-controls {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(220px, 0.8fr);
  gap: 10px;
  padding: 0 12px 10px;
}

.tag-preview-controls label,
.tag-preview-text {
  display: grid;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.tag-preview-text {
  padding: 0 12px 10px;
}

.tag-preview-actions {
  display: flex;
  gap: 8px;
  padding: 0 12px 12px;
}

.tag-preview-result {
  display: grid;
  gap: 8px;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--border);
}

.tag-preview-summary,
.tag-preview-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
}

.tag-preview-summary {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.preview-items {
  display: grid;
  gap: 8px;
}

.preview-item {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}

.preview-item-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.preview-item-head strong {
  color: var(--text-primary);
  font-size: 13px;
}

.preview-item p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.preview-more {
  color: var(--text-muted);
  font-size: 12px;
}

.tag-edit-form {
  display: grid;
  gap: 14px;
}

.tag-edit-form label {
  display: grid;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.tag-toggle-row {
  display: flex;
  gap: 24px;
  align-items: center;
}

.tag-toggle-row :deep(.arco-checkbox-label) {
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 6px;
}

@media (max-width: 1100px) {
  .tag-metric-grid,
  .tag-preview-controls {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .tag-metric-grid,
  .tag-preview-controls {
    grid-template-columns: 1fr;
  }
}
</style>
