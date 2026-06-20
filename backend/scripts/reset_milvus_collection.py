"""Reset the Milvus document collection before rebuilding embeddings.

Use this after changing embedding models. It removes vector data and resets
terminal document records to `uploaded` so they can be processed again.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from pymilvus import MilvusClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.core.database import get_db
from app.rag.vectorstores.embedding_fingerprint import clear_fingerprint

COLLECTION_NAME = "general_documents"


async def reset_document_statuses():
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE general_documents
            SET status = 'uploaded',
                chunk_count = 0,
                image_count = 0,
                error_msg = '',
                error_code = '',
                last_failed_stage = '',
                cleanup_status = ''
            WHERE status IN ('completed', 'failed')
              AND cleanup_status != 'milvus_delete_failed'
            """
        )
        await db.commit()
        return cursor.rowcount


def drop_collection():
    client = MilvusClient(uri=settings.MILVUS_URI)
    if not client.has_collection(collection_name=COLLECTION_NAME):
        print(f"Collection {COLLECTION_NAME!r} does not exist; nothing to drop.")
        return False
    client.drop_collection(collection_name=COLLECTION_NAME)
    print(f"Dropped Milvus collection {COLLECTION_NAME!r}.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Reset Milvus vectors before rebuilding embeddings")
    parser.add_argument(
        "--drop-only",
        action="store_true",
        help="Only drop the Milvus collection; do not reset document statuses.",
    )
    args = parser.parse_args()

    drop_collection()
    clear_fingerprint()
    if args.drop_only:
        print("Document statuses were not changed; embedding fingerprint cleared.")
        return

    count = asyncio.run(reset_document_statuses())
    print(f"Reset {count} document record(s) to uploaded. Re-process them to rebuild vectors.")


if __name__ == "__main__":
    main()
