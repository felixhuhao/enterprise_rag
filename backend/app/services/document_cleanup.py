"""Document cleanup helpers for local artifacts and Milvus vectors."""

from __future__ import annotations

import os
import shutil

from app.config import settings


def delete_local_artifacts(document_id: str) -> None:
    """Delete uploaded and parsed artifacts. Idempotent."""
    for path in (
        os.path.join(settings.GENERAL_UPLOAD_DIR, document_id),
        os.path.join(settings.GENERAL_PARSED_DIR, document_id),
    ):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def delete_from_milvus(document_id: str) -> None:
    from app.rag.vectorstores.general_milvus import delete_by_document_id

    delete_by_document_id(document_id)
