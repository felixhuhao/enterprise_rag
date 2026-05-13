import json
import random
import time
from typing import List, Dict

from langchain_core.documents import Document

from milvus_db.collections_operator import client, COLLECTION_NAME
from utils.embedding_utils import VLEmbeddingClient

# 限流配置
MAX_429_RETRIES = 3
BASE_BACKOFF = 2.0


def doc_to_dict(doc: Document) -> Dict:
    """将 Document 转为 Milvus 写入格式"""
    meta = doc.metadata

    # 拼接标题层级
    headers = []
    for level in range(1, 4):
        val = meta.get(f"Header {level}", "").strip()
        if val:
            headers.append(val)
    title = " > ".join(headers)

    # 文本前面加上标题，提升 BM25 命中率
    text = doc.page_content
    if title and text != "[图片]":
        text = f"{title}：{text}"

    return {
        "text": text,
        "source": meta.get("source", ""),
        "title": title,
        "image_paths": json.dumps(meta.get("image_paths", []), ensure_ascii=False),
    }


def delete_by_source(source: str):
    """按 source 删除已有记录，防止重复插入同一份 PDF"""
    res = client.delete(
        collection_name=COLLECTION_NAME,
        filter=f'source == "{source}"',
    )
    count = res.get("delete_count", res) if isinstance(res, dict) else getattr(res, "delete_count", 0)
    # flush 确保删除生效后再插入，否则新旧数据会并存
    client.flush(collection_name=COLLECTION_NAME)
    print(f"[Milvus] 清理旧数据 source={source}, 删除 {count} 条")


def write_to_milvus(data: List[Dict], dedup_by_source: bool = True):
    """
    批量写入 Milvus

    Args:
        data: 要写入的记录列表
        dedup_by_source: 是否先按 source 删除旧数据（默认开启）
    """
    if not data:
        print("[Milvus] 没有可写入的数据")
        return

    if dedup_by_source:
        sources = set(d.get("source", "") for d in data if d.get("source"))
        for src in sources:
            delete_by_source(src)

    result = client.insert(collection_name=COLLECTION_NAME, data=data)
    print(f"[Milvus] 成功插入 {result['insert_count']} 条记录")
    return result


def do_save_to_milvus(documents: List[Document]) -> List[Dict]:
    """
    Document 列表 → 向量化 → 写入 Milvus

    1. 文档转为字典
    2. 调用 qwen3-vl-embedding 生成 dense 向量（图文融合）
    3. 写入 Milvus（sparse 向量由 BM25 自动生成）
    """
    embedding_client = VLEmbeddingClient()
    records = []

    for i, doc in enumerate(documents):
        row = doc_to_dict(doc)

        # 生成 dense 向量（带重试）
        dense = _embed_with_retry(embedding_client, doc, i)
        if dense is None:
            continue

        row["dense"] = dense
        records.append(row)

        if (i + 1) % 5 == 0:
            print(f"[进度] 已处理 {i + 1}/{len(documents)}")

    write_to_milvus(records)
    return records


def _embed_with_retry(client: VLEmbeddingClient, doc: Document, idx: int):
    """带 429 重试的向量化"""
    image_paths = doc.metadata.get("image_paths", [])
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            if image_paths:
                return client.embed_text_with_images(doc.page_content, image_paths)
            else:
                return client.embed_text(doc.page_content)
        except RuntimeError as e:
            if "429" in str(e) and attempt < MAX_429_RETRIES:
                backoff = BASE_BACKOFF * (2 ** attempt) * (0.8 + random.random() * 0.4)
                print(f"[429重试] 文档#{idx} 第{attempt + 1}次，等待 {backoff:.1f}s")
                time.sleep(backoff)
            else:
                print(f"[错误] 文档#{idx} 向量化失败: {e}")
                return None
