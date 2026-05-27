"""Smoke test the configured embedding model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings


def main():
    print(f"embedding_model_path={settings.EMBEDDING_MODEL_PATH}")
    print(f"dim={settings.EMBEDDING_DIM}")
    print(f"device={settings.EMBEDDING_DEVICE}")
    from app.rag.embeddings.dense_embedding import dense_embedding

    texts = ["这是一个测试文档。", "报销政策的上限是多少？"]
    vectors = dense_embedding.embed_documents(texts, chunk_size=2)
    dims = [len(v) for v in vectors]
    print(f"vectors={len(vectors)}")
    print(f"dims={dims}")
    if len(vectors) != len(texts):
        raise SystemExit("embedding count mismatch")
    if any(dim != settings.EMBEDDING_DIM for dim in dims):
        raise SystemExit("embedding dim mismatch")


if __name__ == "__main__":
    main()
