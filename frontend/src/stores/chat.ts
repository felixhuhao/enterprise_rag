/**
 * 聊天状态管理 (Pinia Store)
 *
 * 管理聊天会话、消息列表、SSE 流式状态、人工审批状态
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { createSession } from '../api/chat'
import { connectSSE, type SSEEvent } from '../utils/sse'

/** 聊天消息结构 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'  // 用户消息 | AI 回复 | 工具调用结果
  content: string
  toolName?: string                      // 仅 tool 类型有值
}

export const useChatStore = defineStore('chat', () => {
  // ---- 响应式状态 ----

  /** 当前会话 ID（对应后端 LangGraph 的 thread_id） */
  const sessionId = ref<string | null>(null)

  /** 消息列表 */
  const messages = ref<ChatMessage[]>([])

  /** 是否正在流式接收中 */
  const isStreaming = ref(false)

  /** 是否处于人工审批中断状态 */
  const isInterrupted = ref(false)

  /** 触发中断时的评估分数 */
  const interruptScore = ref<number | null>(null)

  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 当前 SSE 连接的 AbortController，用于取消流 */
  let abortController: AbortController | null = null

  // ---- Actions ----

  /** 初始化会话（如果尚未创建则调后端新建） */
  async function initSession() {
    if (sessionId.value) return
    const session = await createSession()
    sessionId.value = session.session_id
  }

  /**
   * 发送用户消息
   *
   * 流程：添加用户消息 → 添加 AI 占位 → 发起 SSE 连接 → 流式更新
   */
  function sendMessage(text: string, imageBase64?: string) {
    if (!sessionId.value || isStreaming.value) return

    // 添加用户消息到列表
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: imageBase64 ? `${text || ''} [图片]` : text,
    })

    isStreaming.value = true
    isInterrupted.value = false
    error.value = null

    // 添加 AI 消息占位（流式过程中逐步更新内容）
    const assistantId = crypto.randomUUID()
    messages.value.push({ id: assistantId, role: 'assistant', content: '' })

    // 发起 SSE 连接
    abortController = connectSSE(
      '/chat',
      { session_id: sessionId.value, text, image_base64: imageBase64 },
      (event: SSEEvent) => handleEvent(event, assistantId),
      (err: any) => {
        isStreaming.value = false
        error.value = err.message || '连接失败'
      },
      () => {
        isStreaming.value = false
      },
    )
  }

  /**
   * 处理 SSE 事件，更新消息列表和状态
   *
   * @param event SSE 事件对象
   * @param assistantId 当前 AI 消息的 ID（用于更新占位内容）
   */
  function handleEvent(event: SSEEvent, assistantId?: string) {
    switch (event.type) {
      case 'tool_call':
        // 工具调用结果：插入为 tool 类型消息（显示为折叠卡片）
        messages.value.push({
          id: crypto.randomUUID(),
          role: 'tool',
          content: event.data.content,
          toolName: event.data.tool_name,
        })
        break

      case 'assistant_chunk':
        // AI 回复片段：更新对应的占位消息内容（最终会替换为完整内容）
        const msg = messages.value.find((m) => m.id === assistantId)
        if (msg) {
          msg.content = event.data.content
        }
        break

      case 'interrupt':
        // 评估分数低，工作流中断等待人工审批
        isInterrupted.value = true
        interruptScore.value = event.data.score
        isStreaming.value = false
        break

      case 'message_end':
        // 流式处理完成
        isStreaming.value = false
        break

      case 'error':
        error.value = event.data.message
        isStreaming.value = false
        break
    }
  }

  /**
   * 人工审批操作
   *
   * @param action 'approve' 批准 | 'reject' 拒绝（触发网络搜索重生成）
   */
  function approveOrReject(action: 'approve' | 'reject') {
    if (!sessionId.value || isStreaming.value) return

    isInterrupted.value = false
    isStreaming.value = true

    // reject 时需要 assistant 占位（会生成新的回复），approve 直接结束不需要
    let assistantId: string | undefined
    if (action === 'reject') {
      assistantId = crypto.randomUUID()
      messages.value.push({ id: assistantId, role: 'assistant', content: '' })
    }

    const path = action === 'approve' ? '/chat/approve' : '/chat/reject'
    abortController = connectSSE(
      path,
      { session_id: sessionId.value },
      (event: SSEEvent) => handleEvent(event, assistantId),
      (err: any) => {
        isStreaming.value = false
        error.value = err.message || '连接失败'
      },
      () => {
        isStreaming.value = false
      },
    )
  }

  /** 中止当前流式连接 */
  function stopStreaming() {
    abortController?.abort()
    isStreaming.value = false
  }

  /** 清空所有消息和状态（开始新对话） */
  function clearMessages() {
    messages.value = []
    sessionId.value = null
    isInterrupted.value = false
    interruptScore.value = null
    error.value = null
  }

  return {
    sessionId,
    messages,
    isStreaming,
    isInterrupted,
    interruptScore,
    error,
    initSession,
    sendMessage,
    approveOrReject,
    stopStreaming,
    clearMessages,
  }
})
