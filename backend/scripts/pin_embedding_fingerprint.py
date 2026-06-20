"""Pin the embedding fingerprint to the current settings without dropping data.

Use this when upgrading on an UNCHANGED embedding provider (e.g. existing
BGE-M3 collection, still on BGE-M3) so the vector-space fingerprint guard does
not block query/upsert. Only run it when the existing indexed data was actually
produced by the currently configured provider/model/dim.

For provider switches (BGE-M3 → Qwen), reset + reindex instead:
    python scripts/reset_milvus_collection.py
"""

import argparse
import json
import sys
from pathlib import Path

from pymilvus import MilvusClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.rag.vectorstores.embedding_fingerprint import (
    FINGERPRINT_KEY,
    current_fingerprint,
    record_fingerprint,
    stored_fingerprint,
)

COLLECTION_NAME = "general_documents"


def describe_current() -> str:
    fp = json.loads(current_fingerprint())
    return (
        f"  collection:       {COLLECTION_NAME}\n"
        f"  provider:         {fp['provider']}\n"
        f"  model:            {fp['model']}\n"
        f"  dim:              {fp['dim']}\n"
        f"  fingerprint key:  {FINGERPRINT_KEY}"
    )


def collection_exists() -> bool:
    client = MilvusClient(uri=settings.MILVUS_URI)
    return bool(client.has_collection(collection_name=COLLECTION_NAME))


def pin() -> str:
    """Record the current fingerprint. Returns a human-readable result line.

    Refuses if the collection does not exist (nothing to pin against).
    """
    if not collection_exists():
        raise RuntimeError(
            f"Milvus collection {COLLECTION_NAME!r} does not exist; "
            "ingest a document first or run without this tool."
        )
    prev = stored_fingerprint()
    if prev is not None and prev != current_fingerprint():
        raise RuntimeError(
            "A different fingerprint is already stored. Pinning a mismatched "
            "fingerprint would corrupt vector-space safety. Run "
            "`python scripts/reset_milvus_collection.py` instead."
        )
    record_fingerprint()
    return "Pinned embedding fingerprint to current settings."


def main():
    parser = argparse.ArgumentParser(
        description="Pin the embedding fingerprint to current settings (non-destructive)."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive: skip the confirmation prompt (for Docker/CI).",
    )
    args = parser.parse_args()

    print("Current embedding settings:")
    print(describe_current())
    print()
    print(
        "WARNING: only pin if the existing indexed data was produced by the "
        "settings shown above. Otherwise reset and reindex "
        "(`scripts/reset_milvus_collection.py`)."
    )

    if not args.yes:
        answer = input("\nProceed with pinning? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted; fingerprint not changed.")
            return

    try:
        msg = pin()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(msg)


if __name__ == "__main__":
    main()
