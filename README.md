# Multimodal RAG Pro

企业级多模态 RAG 系统前端，基于 FastAPI + Vue 3 + Arco Design 构建。

后端通过 `sys.path` 引用父项目 `D:\CodeProjects\multimodel_rag` 的 LangGraph 工作流，不修改原有代码。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | FastAPI + uvicorn | REST API + SSE 流式 |
| 工作流 | LangGraph (父项目) | 多节点有向图，含人工审批中断 |
| 前端 | Vue 3 + TypeScript | Composition API |
| UI 框架 | Arco Design Vue | 字节跳动开源企业级组件库 |
| 状态管理 | Pinia | Vue 3 官方推荐 |
| 构建工具 | Vite | 快速 HMR |

## 项目结构

```
multimodel_rag_pro/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口, CORS, lifespan
│   │   ├── config.py            # pydantic-settings 配置
│   │   ├── deps.py              # 依赖注入 (Token 鉴权)
│   │   ├── api/
│   │   │   ├── router.py        # 路由聚合
│   │   │   ├── chat.py          # POST /api/chat (SSE 流式)
│   │   │   ├── approval.py      # POST /api/chat/approve | reject
│   │   │   └── sessions.py      # 会话 CRUD
│   │   ├── core/
│   │   │   ├── graph_manager.py # LangGraph 封装 (sys.path 注入父项目)
│   │   │   └── session_manager.py
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic 数据模型
│   │   └── services/
│   │       ├── chat_service.py  # 核心流式生成器
│   │       └── approval_service.py
│   ├── .env                     # 环境变量
│   ├── requirements.txt
│   └── run.py                   # uvicorn 启动入口
│
└── frontend/
    ├── src/
    │   ├── main.ts              # Vue 应用入口
    │   ├── App.vue
    │   ├── router/index.ts      # 路由配置
    │   ├── api/
    │   │   ├── client.ts        # axios 实例
    │   │   └── chat.ts          # 会话 API 调用
    │   ├── stores/
    │   │   └── chat.ts          # Pinia 聊天状态管理
    │   ├── utils/
    │   │   └── sse.ts           # fetch-based SSE 处理器
    │   ├── components/
    │   │   ├── layout/
    │   │   │   └── AppLayout.vue  # 侧边栏 + 主内容布局
    │   │   └── chat/
    │   │       ├── ChatView.vue     # 聊天页主容器
    │   │       ├── MessageList.vue  # 消息列表
    │   │       ├── MessageBubble.vue # 消息气泡 (Markdown)
    │   │       ├── ToolCallCard.vue  # 工具调用折叠卡片
    │   │       ├── ApprovalPanel.vue # 人工审批面板
    │   │       └── ChatInput.vue     # 输入框 + 图片上传
    │   └── styles/
    │       └── global.css
    ├── vite.config.ts           # Vite 配置 (含 API 代理)
    └── package.json
```

## 核心流程

```
用户输入 → ChatInput → SSE POST /api/chat
  → FastAPI → GraphManager → LangGraph 工作流 (父项目)
    → process_input → first_chatbot → search_context → retriever_node
    → third_chatbot → evaluate_node
      → 分数 >= 0.8: 直接返回
      → 分数 0.6~0.8: 中断，等待人工审批 (SSE interrupt 事件)
      → 分数 < 0.6: 自动 reject → fourth_chatbot (网络搜索)
  ← SSE 流式返回: tool_call / assistant_chunk / interrupt / message_end
```

## SSE 事件协议

| 事件类型 | 说明 | 数据 |
|---------|------|------|
| `message_start` | 开始处理 | - |
| `tool_call` | 工具调用结果 | `{tool_name, content}` |
| `assistant_chunk` | AI 回复片段 | `{content}` |
| `interrupt` | 需要人工审批 | `{reason, score}` |
| `message_end` | 处理完成 | `{from_web_search}` |
| `error` | 错误 | `{message}` |

## API 端点

| 方法 | 路径 | 说明 |
|-----|------|------|
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions` | 列出会话 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/chat` | 发送消息 (SSE) |
| POST | `/api/chat/approve` | 批准回复 (SSE) |
| POST | `/api/chat/reject` | 拒绝回复 (SSE) |

所有接口需携带 `Authorization: Bearer <token>` 头。

## 启动方式

```bash
# 1. 后端 (port 8900)
cd D:\CodeProjects\multimodel_rag_pro\backend
pip install -r requirements.txt
python run.py

# 2. 前端 (port 5173, 自动代理到后端)
cd D:\CodeProjects\multimodel_rag_pro\frontend
npm install
npm run dev
```

浏览器访问 http://localhost:5173

## 配置

`backend/.env`:
```env
PARENT_PROJECT_PATH=D:\CodeProjects\multimodel_rag
API_TOKEN=rag-pro-secret-token
```

## MVP 状态

- [x] FastAPI 后端骨架
- [x] LangGraph 多会话封装
- [x] SSE 流式聊天 API
- [x] 人工审批 API (approve/reject)
- [x] Vue 3 + Arco Design 前端
- [x] 聊天界面 (消息、工具调用、审批)
- [x] 图片上传支持
- [x] 知识库管理页 (上传 PDF → OCR → Milvus 入库)
- [x] 评估看板页 (ECharts 可视化分数分布和趋势)
- [x] 设置页 (运行时配置、Token 管理)
- [x] 持久化会话 (SQLite)
