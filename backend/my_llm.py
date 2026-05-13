from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from tavily import TavilyClient
from zhipuai import ZhipuAI

from app.config import settings

# 聊天模型：优先使用本地模型，否则使用 DashScope 云端模型
if settings.LOCAL_MODEL_URL:
    multiModal_llm = ChatOpenAI(
        model=settings.LOCAL_MODEL_NAME,
        api_key="empty",
        base_url=settings.LOCAL_MODEL_URL,
        timeout=settings.CHAT_TIMEOUT,
        max_retries=3,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
else:
    multiModal_llm = ChatOpenAI(
        model=settings.CHAT_MODEL,
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.DASHSCOPE_BASE_URL,
        timeout=settings.CHAT_TIMEOUT,
        max_retries=3,
    )

eval_llm = ChatOpenAI(
    model=settings.EVAL_MODEL,
    api_key=settings.DASHSCOPE_API_KEY,
    base_url=settings.DASHSCOPE_BASE_URL,
    timeout=settings.EVAL_TIMEOUT,
    max_retries=3,
)

text_embedding = OpenAIEmbeddings(
    api_key=settings.DASHSCOPE_API_KEY,
    base_url=settings.DASHSCOPE_BASE_URL,
    model=settings.EMBEDDING_MODEL,
    dimensions=settings.EMBEDDING_DIM,
    check_embedding_ctx_length=False,
)

zhipuai_client = ZhipuAI(api_key=settings.ZHIPU_API_KEY, base_url=settings.ZHIPU_BASE_URL)
tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
