import base64
import os
from typing import List, Optional, Tuple

import dashscope
from http import HTTPStatus
from langchain_core.documents import Document

from app.config import settings
from utils.log_utils import log

MODEL_NAME = "qwen3-vl-embedding"
INSTRUCTION = "Represent the user's input for retrieval."


class VLEmbeddingClient:
    """基于 DashScope qwen3-vl-embedding 的多模态 Embedding 客户端"""

    def __init__(self, api_key: Optional[str] = None):
        dashscope.api_key = api_key or settings.DASHSCOPE_API_KEY

    def _call_api(self, input_data: list, enable_fusion: bool = False) -> list:
        """调用 DashScope MultiModalEmbedding API 的统一入口

        Args:
            input_data: 已格式化的输入列表
            enable_fusion: 是否启用图文融合
        Returns:
            embedding 向量
        """
        resp = dashscope.MultiModalEmbedding.call(
            model=MODEL_NAME,
            input=input_data,
            enable_fusion=enable_fusion or None,
        )
        self._check_response(resp)
        return resp.output["embeddings"][0]["embedding"]

    @staticmethod
    def _format_text(text: str) -> dict:
        """格式化文本输入（加 INSTRUCTION 前缀）"""
        return {"text": f"Instruct: {INSTRUCTION}\nQuery: {text}"}

    def embed_text(self, text: str) -> List[float]:
        """纯文本向量化"""
        return self._call_api([self._format_text(text)])

    def embed_text_with_images(self, text: str, image_paths: List[str]) -> List[float]:
        """文本+图片融合向量化

        Args:
            text: 文本内容
            image_paths: 图片列表，支持文件路径和 data URI 两种格式
        """
        contents = []
        for img_path in image_paths:
            if img_path.startswith("data:"):
                # 已经是 data URI，直接使用
                contents.append({"image": img_path})
            else:
                # 文件路径，读取并转换
                contents.append({"image": self._read_image_as_data_uri(img_path)})
        if text:
            contents.append(self._format_text(text))
        return self._call_api(contents, enable_fusion=True)

    def embed_documents(self, documents: List[Document]) -> List[List[float]]:
        """批量向量化 Document 列表，根据 image_paths 自动路由"""
        embeddings = []
        for i, doc in enumerate(documents):
            image_paths = doc.metadata.get("image_paths", [])
            if image_paths:
                emb = self.embed_text_with_images(doc.page_content, image_paths)
            else:
                emb = self.embed_text(doc.page_content)
            embeddings.append(emb)
            if (i + 1) % 5 == 0:
                print(f"已向量化 {i + 1}/{len(documents)} 个文档")
        return embeddings

    def embed_query(self, query_text: str) -> List[float]:
        """用户查询向量化（纯文本）"""
        return self.embed_text(query_text)

    @staticmethod
    def _read_image_as_data_uri(img_path: str) -> str:
        """读取本地图片文件，转为 data URI 格式的 base64 字符串"""
        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
        mime = mime_map.get(ext, "image/png")
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _check_response(resp):
        """检查 DashScope API 响应状态"""
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope API 调用失败 (status={resp.status_code}): "
                f"code={resp.code}, message={resp.message}"
            )


# 全局单例
_vl_client = VLEmbeddingClient()


def embed_for_knowledge_base(
    input_data: list,
) -> Tuple[bool, Optional[list], Optional[int], Optional[float]]:
    """调用 DashScope 多模态向量化 API（容错版本，返回元组而非抛异常）

    适用于知识库检索等场景：调用方需要自行处理失败情况。

    Args:
        input_data: 输入数据列表，格式为 [{'text': '...'}] 或 [{'image': 'data:...'}]

    Returns:
        (ok, embedding, status_code, retry_after) 元组
    """
    try:
        formatted = []
        for item in input_data:
            if "text" in item:
                formatted.append(_vl_client._format_text(item["text"]))
            elif "image" in item:
                formatted.append({"image": item["image"]})

        resp = dashscope.MultiModalEmbedding.call(
            model=MODEL_NAME,
            input=formatted,
        )

        if resp.status_code == HTTPStatus.OK:
            embedding = resp.output["embeddings"][0]["embedding"]
            return True, embedding, resp.status_code, None

        log.warning(
            f"DashScope 调用失败: code={resp.code}, message={resp.message}"
        )
        retry_after = None
        if resp.headers and isinstance(resp.headers, dict):
            retry_after = resp.headers.get("Retry-After") or resp.headers.get(
                "retry-after"
            )
        return False, None, resp.status_code, retry_after

    except Exception as e:
        log.error(f"DashScope 调用异常: {e}")
        return False, None, None, None
