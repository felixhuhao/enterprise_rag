"""
应用配置模块

使用 pydantic-settings 统一管理所有配置项，支持从 .env 文件和环境变量读取。
涵盖：API 鉴权、CORS、数据库、LLM 模型、Milvus 向量库等。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    全局配置类

    所有配置项均有默认值，可通过 .env 文件或环境变量覆盖。
    """

    # ---- 应用基本配置 ----
    API_TOKEN: str = "enterprise-rag-dev-token"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    GENERAL_UPLOAD_DIR: str = "./data/general_uploads"
    GENERAL_PARSED_DIR: str = "./data/general_parsed"
    DATABASE_PATH: str = "./data/app.db"

    # ---- LLM 模型配置 ----
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    CHAT_MODEL: str = "qwen-plus"
    CHAT_TIMEOUT: int = 180
    # 本地模型（vLLM 部署），留空则使用 DashScope 云端模型
    LOCAL_MODEL_URL: str = ""
    LOCAL_MODEL_NAME: str = ""

    # ---- Embedding 配置 ----
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIM: int = 1024
    MINERU_BASE_URL: str = "https://mineru.net/api/v4"
    MINERU_API_TOKEN: str = ""
    MINERU_MODEL_VERSION: str = "vlm"
    MINERU_POLL_INTERVAL: int = 3
    MINERU_POLL_TIMEOUT: int = 1800
    MINERU_UPLOAD_TIMEOUT: int = 300
    MINERU_DOWNLOAD_TIMEOUT: int = 300

    # ---- Milvus 向量数据库 ----
    MILVUS_URI: str = "http://localhost:19530"

    # ---- Markdown Zip 配置 ----
    MD_ZIP_MAX_SIZE_MB: int = 50

    # ---- 图片描述配置 ----
    IMAGE_DESCRIPTION_ENABLED: bool = True
    IMAGE_DESCRIPTION_MODEL: str = "qwen3-vl-flash"
    IMAGE_DESCRIPTION_CONCURRENCY: int = 3
    IMAGE_DESCRIPTION_TIMEOUT: int = 30
    IMAGE_DESCRIPTION_MAX_SIZE_MB: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 全局单例
settings = Settings()
