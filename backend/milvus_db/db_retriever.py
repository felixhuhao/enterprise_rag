import os
from typing import List, Dict, Any

from pymilvus import AnnSearchRequest, WeightedRanker

from milvus_db.collections_operator import client, COLLECTION_NAME
from utils.embedding_utils import VLEmbeddingClient


class MilvusRetriever:
    """混合检索器：dense 向量 + BM25 稀疏向量"""

    def __init__(self, top_k: int = 5, dense_weight: float = 1.0, sparse_weight: float = 1.0):
        self.top_k = top_k
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.embedding_client = VLEmbeddingClient()

    def dense_search(self, query_embedding: List[float], limit: int = 10) -> List[Dict]:
        """纯向量检索"""
        res = client.search(
            collection_name=COLLECTION_NAME,
            data=[query_embedding],
            anns_field="dense",
            limit=limit,
            output_fields=["text", "source", "title", "image_paths"],
            search_params={"metric_type": "COSINE", "params": {"nprobe": 10}},
        )
        return self._parse_results(res[0])

    def hybrid_search(self, query_embedding: List[float], query_text: str, limit: int = 10) -> List[Dict]:
        """混合检索：dense + BM25 加权融合"""
        dense_req = AnnSearchRequest(
            [query_embedding], "dense",
            {"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=limit,
        )
        sparse_req = AnnSearchRequest(
            [query_text], "sparse",
            {"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
            limit=limit,
        )
        reranker = WeightedRanker(self.sparse_weight, self.dense_weight)

        res = client.hybrid_search(
            collection_name=COLLECTION_NAME,
            reqs=[sparse_req, dense_req],
            ranker=reranker,
            limit=limit,
            output_fields=["text", "source", "title", "image_paths"],
        )
        return self._parse_results(res[0])

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """
        统一检索入口

        Args:
            query: 文本查询 or 本地图片路径
        Returns:
            检索结果列表
        """
        is_image = os.path.isfile(query)

        if is_image:
            # 图片查询：直接传文件路径给 embedding，只做 dense 检索
            embedding = self.embedding_client.embed_text_with_images("", [query])
            return self.dense_search(embedding, limit=self.top_k)
        else:
            # 文本查询：混合检索
            embedding = self.embedding_client.embed_query(query)
            return self.hybrid_search(embedding, query, limit=self.top_k)

    @staticmethod
    def _hit_score(hit) -> Any:
        """MilvusClient 返回 dict 时用 distance；部分 API 用 score。"""
        if isinstance(hit, dict):
            return hit.get("distance", hit.get("score"))
        return getattr(hit, "distance", None) or getattr(hit, "score", None)

    @staticmethod
    def _parse_results(hits) -> List[Dict]:
        results = []
        for hit in hits:
            raw = hit["entity"] if isinstance(hit, dict) else hit.entity
            entity = raw if isinstance(raw, dict) else dict(raw or {})
            results.append({
                "score": MilvusRetriever._hit_score(hit),
                "text": entity.get("text"),
                "source": entity.get("source"),
                "filename": entity.get("source"),   # 兼容 workflow 中引用的 filename
                "title": entity.get("title"),
                "image_paths": entity.get("image_paths"),  # JSON array string
            })
        return results


def _print_results(label: str, docs: List[Dict]):
    print(f"{'=' * 20} {label} {'=' * 20}")
    for d in docs:
        sc = d["score"]
        sc_s = f"{sc:.4f}" if isinstance(sc, (int, float)) else str(sc)
        title = d["title"] or ""
        body = (d["text"] or "")[:80]
        imgs = d.get("image_paths", "")
        img_tag = " [含图片]" if imgs and imgs != "[]" else ""
        print(f"[score={sc_s}] {title}{img_tag}")
        print(f"  {body}...")
    print()


if __name__ == "__main__":
    import sys

    retriever = MilvusRetriever(top_k=3)

    # 支持命令行传入查询，否则跑全部 case
    custom_query = sys.argv[1] if len(sys.argv) >= 2 else None

    # ---- 各类检索 Case ----
    cases = [
        # (描述, 查询内容, 期望命中的检索类型)
        ("语义检索：自然语言提问", "开通港股通需要满足什么条件", "dense"),
        ("语义检索：对比类问题", "港股交易时间和A股有什么区别", "dense"),
        ("关键词检索：精确术语", "印花税", "sparse"),
        ("关键词检索：精确数值", "0.1%", "sparse"),
        ("关键词检索：具体规则名称", "竞价限价盘", "sparse"),
        ("混合检索：自然语言含关键词", "港股通的交易费用印花税是多少", "hybrid"),
        ("混合检索：具体规则问法", "碎股可以买入吗", "hybrid"),
        ("语义检索：流程类问题", "港股卖出后资金什么时候可以用来买A股", "dense"),
        ("关键词检索：股票代码规则", "每手股数", "sparse"),
        ("混合检索：时间规则", "开市前时段几点开始", "hybrid"),
    ]

    if custom_query:
        # 命令行模式：只跑用户指定的查询
        docs = retriever.retrieve(custom_query)
        _print_results(f"检索: {custom_query}", docs)
    else:
        # 全量 case 模式
        for label, query, expected in cases:
            docs = retriever.retrieve(query)
            _print_results(f"[{expected}] {label}: {query}", docs)

        # 图片检索（如果文件存在）
        image_path = os.path.join(os.path.dirname(__file__), "收市竞价交易.png")
        if os.path.isfile(image_path):
            image_docs = retriever.retrieve(image_path)
            _print_results(f"图片检索: {os.path.basename(image_path)}", image_docs)
        else:
            print(f"[跳过] 图片不存在: {image_path}")
