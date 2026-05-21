/**
 * 知识查询聊天状态管理 (Pinia Store)
 *
 * 管理 query chat 的会话、消息列表、SSE 流式状态
 * 后端 SSE 事件: message_start | retrieval_step | delta | citations | message_end
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { connectSSE, type SSEEvent } from '../utils/sse'

/** 引用信息 */
export interface Citation {
  id: string
  document_id?: string
  file_title?: string
  section_title?: string
  table_id?: string
  source_type?: string
}

/** 聊天消息 */
export interface QueryChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

/** 检索步骤信息 */
export interface RetrievalInfo {
  results_count: number
  entity: string
  rewritten_query: string
  search_mode: string
  search_mode_hyde: string
}

/** rerank debug 条目 */
export interface RerankItem {
  index: number
  file_title: string
  section_title: string
  source_type: string
  llm_score: number
  rrf_score: number
  final_score: number
}

export const useQueryChatStore = defineStore('queryChat', () => {
  // ---- 响应式状态 ----

  /** 当前会话 ID（前端生成 UUID，不依赖后端创建） */
  const sessionId = ref('')

  /** 消息列表 */
  const messages = ref<QueryChatMessage[]>([])

  /** 是否正在流式接收 */
  const isStreaming = ref(false)

  /** 当前检索步骤信息 */
  const retrievalInfo = ref<RetrievalInfo | null>(null)

  /** rerank debug 信息 */
  const rerankDebug = ref<RerankItem[]>([])

  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 当前 SSE 连接的 AbortController */
  let abortController: AbortController | null = null

  /** 当前 AI 消息 ID（用于 SSE 流式更新） */
  let currentAssistantId = ''

  // ---- Actions ----

  /** 确保有 sessionId */
  function ensureSession() {
    if (!sessionId.value) {
      sessionId.value = crypto.randomUUID()
    }
  }

  /** 发送查询消息 */
  function sendMessage(query: string) {
    if (!query.trim() || isStreaming.value) return
    ensureSession()

    // 添加用户消息
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: query.trim(),
    })

    isStreaming.value = true
    error.value = null
    retrievalInfo.value = null

    // 添加 AI 占位消息
    currentAssistantId = crypto.randomUUID()
    messages.value.push({ id: currentAssistantId, role: 'assistant', content: '' })

    // 发起 SSE 连接
    abortController = connectSSE(
      '/query/chat/stream',
      { session_id: sessionId.value, query: query.trim() },
      (event: SSEEvent) => handleEvent(event),
      (err: any) => {
        isStreaming.value = false
        error.value = err.message || '连接失败'
      },
      () => {
        isStreaming.value = false
      },
    )
  }

  /** 处理 SSE 事件（扁平结构，直接访问 event 属性） */
  function handleEvent(event: SSEEvent) {
    switch (event.type) {
      case 'message_start':
        retrievalInfo.value = null
        rerankDebug.value = []
        break

      case 'retrieval_step':
        retrievalInfo.value = {
          results_count: (event as any).results_count ?? 0,
          entity: (event as any).entity ?? '',
          rewritten_query: (event as any).rewritten_query ?? '',
          search_mode: (event as any).search_mode ?? '',
          search_mode_hyde: (event as any).search_mode_hyde ?? '',
        }
        break

      case 'delta':
        {
          const msg = messages.value.find((m) => m.id === currentAssistantId)
          if (msg) {
            msg.content += (event as any).content ?? ''
          }
        }
        break

      case 'rerank':
        rerankDebug.value = (event as any).results ?? []
        break

      case 'citations':
        {
          const msg = messages.value.find((m) => m.id === currentAssistantId)
          if (msg) {
            msg.citations = (event as any).citations ?? []
          }
        }
        break

      case 'message_end':
        isStreaming.value = false
        break

      case 'error':
        error.value = (event as any).message ?? '未知错误'
        isStreaming.value = false
        break
    }
  }

  /** 中止当前流式连接 */
  function stopStreaming() {
    abortController?.abort()
    isStreaming.value = false
  }

  /** 清空所有消息和状态 */
  function clearMessages() {
    messages.value = []
    sessionId.value = ''
    retrievalInfo.value = null
    rerankDebug.value = []
    error.value = null
  }

  return {
    sessionId,
    messages,
    isStreaming,
    retrievalInfo,
    rerankDebug,
    error,
    sendMessage,
    stopStreaming,
    clearMessages,
  }
})
