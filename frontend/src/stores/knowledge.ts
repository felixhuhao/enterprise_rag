/**
 * 知识库状态管理 (Pinia Store)
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listDocuments,
  uploadDocument,
  processDocument,
  deleteDocument as apiDeleteDocument,
  getDocument,
  type KnowledgeDocument,
} from '../api/knowledge'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const documents = ref<KnowledgeDocument[]>([])
  const loading = ref(false)
  const uploading = ref(false)

  async function fetchDocuments() {
    loading.value = true
    try {
      documents.value = await listDocuments()
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    uploading.value = true
    try {
      const doc = await uploadDocument(file)
      documents.value.unshift(doc)
      return doc
    } finally {
      uploading.value = false
    }
  }

  async function process(docId: number) {
    await processDocument(docId)
    // 更新本地状态为 parsing
    const doc = documents.value.find((d) => d.id === docId)
    if (doc) doc.status = 'parsing'
    // 启动轮询
    pollStatus(docId)
  }

  async function remove(docId: number) {
    await apiDeleteDocument(docId)
    documents.value = documents.value.filter((d) => d.id !== docId)
  }

  function pollStatus(docId: number) {
    const timer = setInterval(async () => {
      try {
        const doc = await getDocument(docId)
        const idx = documents.value.findIndex((d) => d.id === docId)
        if (idx >= 0) documents.value[idx] = doc
        if (doc.status === 'completed' || doc.status === 'failed') {
          clearInterval(timer)
        }
      } catch {
        clearInterval(timer)
      }
    }, 3000)
  }

  return {
    documents,
    loading,
    uploading,
    fetchDocuments,
    upload,
    process,
    remove,
  }
})
