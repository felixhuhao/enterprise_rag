<template>
  <div class="alias-page">
    <div v-if="!authStore.isAdmin" class="alias-forbidden">
      <a-empty description="仅管理员可管理实体别名" />
    </div>

    <a-spin v-else :loading="loading" style="width: 100%">
      <div class="alias-tools">
        <div class="alias-form">
          <a-input v-model="aliasInput" placeholder="别名，如 SMIC" allow-clear />
          <a-input v-model="canonicalInput" placeholder="标准实体，如 中芯国际" allow-clear />
          <a-button type="primary" :loading="saving" @click="onCreate">新增</a-button>
          <a-button size="small" :loading="loading" @click="loadAliases">刷新</a-button>
        </div>

        <details class="batch-box">
          <summary>
            <span>批量导入</span>
            <small>每行一个映射：别名,标准实体</small>
          </summary>
          <a-textarea
            v-model="batchInput"
            placeholder="批量导入：每行一个映射，格式为 别名,标准实体"
            :auto-size="{ minRows: 3, maxRows: 6 }"
          />
          <div class="batch-actions">
            <span class="hint">重复映射会自动跳过；标准实体必须已存在于索引。</span>
            <a-button size="small" :loading="batchSaving" @click="onBatchCreate">批量导入</a-button>
          </div>
        </details>
      </div>

      <div :ref="setAliasTableContainer" class="alias-table-wrap">
        <a-table
          :data="records"
          :pagination="{ pageSize: 20 }"
          row-key="id"
          size="small"
          column-resizable
          @column-resize="aliasColumns.onColumnResize"
        >
          <template #columns>
            <a-table-column title="别名" data-index="alias" :width="aliasColumns.columnWidth('alias')" />
            <a-table-column title="标准实体" data-index="canonical_entity" :width="aliasColumns.columnWidth('canonical_entity')" />
            <a-table-column title="来源" data-index="source" :width="aliasColumns.columnWidth('source')">
              <template #cell="{ record }">
                <a-tag size="small">{{ record.source }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column title="创建时间" data-index="created_at" :width="aliasColumns.columnWidth('created_at')" />
            <a-table-column title="操作" data-index="actions" :width="aliasColumns.columnWidth('actions')" align="right">
              <template #cell="{ record }">
                <a-popconfirm content="删除这条别名映射？" @ok="onDelete(record.id)">
                  <a-button size="mini" status="danger">删除</a-button>
                </a-popconfirm>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, type ComponentPublicInstance } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAuthStore } from '../../stores/auth'
import {
  batchCreateEntityAliases,
  createEntityAlias,
  deleteEntityAlias,
  listEntityAliases,
  type EntityAliasRecord,
  type EntityAliasBatchItem,
} from '../../api/entityAliases'
import { useAutoFitColumns } from '../../composables/useAutoFitColumns'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const batchSaving = ref(false)
const records = ref<EntityAliasRecord[]>([])
const aliasInput = ref('')
const canonicalInput = ref('')
const batchInput = ref('')
const aliasColumns = useAutoFitColumns('enterprise-rag:entity-aliases:auto-v1', {
  alias: { width: 180, minWidth: 120, maxWidth: 240 },
  canonical_entity: { width: 360, minWidth: 200, flex: true },
  source: { width: 90, minWidth: 70, maxWidth: 110 },
  created_at: { width: 180, minWidth: 140, maxWidth: 190 },
  actions: { width: 90, minWidth: 72, maxWidth: 110 },
}, { minWidth: 60 })

function setAliasTableContainer(element: Element | ComponentPublicInstance | null) {
  aliasColumns.containerRef.value = element instanceof HTMLElement ? element : null
}

onMounted(async () => {
  if (!authStore.currentUser) await authStore.fetchMe()
  if (authStore.isAdmin) await loadAliases()
})

async function loadAliases() {
  loading.value = true
  try {
    const data = await listEntityAliases()
    records.value = data.records
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  const alias = aliasInput.value.trim()
  const canonical = canonicalInput.value.trim()
  if (!alias || !canonical) {
    Message.warning('请输入别名和标准实体')
    return
  }
  saving.value = true
  try {
    await createEntityAlias(alias, canonical)
    aliasInput.value = ''
    canonicalInput.value = ''
    Message.success('已新增别名映射')
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '新增失败')
  } finally {
    saving.value = false
  }
}

async function onBatchCreate() {
  const items = parseBatchInput(batchInput.value)
  if (!items.length) {
    Message.warning('请输入可导入的映射')
    return
  }
  batchSaving.value = true
  try {
    const result = await batchCreateEntityAliases(items)
    const suffix = result.errors.length ? `，${result.errors.length} 条失败` : ''
    Message.success(`新增 ${result.created} 条，跳过 ${result.skipped} 条${suffix}`)
    batchInput.value = ''
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '批量导入失败')
  } finally {
    batchSaving.value = false
  }
}

async function onDelete(id: number) {
  try {
    await deleteEntityAlias(id)
    Message.success('已删除')
    await loadAliases()
  } catch (err: any) {
    Message.error(err?.response?.data?.detail || '删除失败')
  }
}

function parseBatchInput(value: string): EntityAliasBatchItem[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.includes('\t') ? '\t' : ','
      const [alias = '', canonical = ''] = line.split(separator)
      return {
        alias: alias.trim(),
        canonical_entity: canonical.trim(),
        source: 'admin',
      }
    })
    .filter((item) => item.alias && item.canonical_entity)
}
</script>

<style scoped>
.alias-page {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  height: 100%;
  overflow-y: auto;
  animation: fadeIn 0.22s var(--ease-out);
}

.alias-forbidden { padding: 60px 0; }

.alias-tools {
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
}

.alias-form {
  display: grid;
  grid-template-columns: minmax(150px, 220px) minmax(220px, 1fr) auto auto;
  gap: 8px;
  align-items: center;
}

.alias-table-wrap {
  min-width: 0;
  overflow-x: hidden;
}

.batch-box {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-base);
}

.batch-box summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  cursor: pointer;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  list-style: none;
}

.batch-box summary::-webkit-details-marker {
  display: none;
}

.batch-box summary::after {
  content: '展开';
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}

.batch-box[open] summary::after {
  content: '收起';
}

.batch-box summary small {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 400;
}

.batch-box :deep(.arco-textarea-wrapper) {
  margin: 0 10px;
  width: calc(100% - 20px);
}

.batch-actions {
  padding: 8px 10px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  color: var(--text-muted);
  font-size: 12px;
}
</style>
