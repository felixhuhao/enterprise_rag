"""Seed demo data: upload sample PDFs and process them.

Usage:
    python scripts/seed_demo.py [--api-base URL] [--token TOKEN] [--data-dir PATH]

Steps:
    1. Find all .pdf/.md/.zip files in the demo data directory
    2. For each file:
       a. Check if already uploaded (by filename) — skip if completed
       b. Upload via POST /api/documents/upload (with entity_name)
       c. Process via POST /api/documents/{id}/process
       d. Wait for completion; if failed, retry via /retry (up to MAX_RETRIES)
    3. Print summary
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://localhost:8010/api"
POLL_INTERVAL = 5  # seconds
POLL_TIMEOUT = 600  # 10 minutes per document
MAX_RETRIES = 2  # max retry attempts per document

# Demo data directory auto-detection (in priority order)
_DEMO_DIR_CANDIDATES = [
    "/app/data/enterprise_docs",     # Docker container
    "/app/data/stock reports",       # Docker container (legacy)
    "../data/enterprise_docs",        # cd backend && python scripts/seed_demo.py
    "../data/stock reports",          # cd backend && python scripts/seed_demo.py (legacy)
    "data/enterprise_docs",           # from project root
    "data/stock reports",             # from project root (legacy)
]

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown", ".zip"}

# All intermediate statuses the backend uses
_PROCESSING_STATUSES = (
    "processing", "parsing", "normalizing", "chunking", "embedding", "saving",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_demo_dir(arg_dir: str | None) -> Path:
    """Resolve demo data directory."""
    if arg_dir:
        p = Path(arg_dir)
        if p.is_dir():
            return p
        print(f"ERROR: --data-dir {arg_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    env_dir = os.environ.get("DEMO_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p

    for candidate in _DEMO_DIR_CANDIDATES:
        p = Path(candidate)
        if p.is_dir():
            return p.resolve()

    print(
        "ERROR: Cannot find demo data directory. "
        "Use --data-dir or set DEMO_DATA_DIR environment variable.",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_token(arg_token: str | None) -> str:
    """Resolve API token."""
    if arg_token:
        return arg_token

    # Try reading from .env files
    for env_path in [Path(".env"), Path("../.env"), Path("../../.env")]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("API_TOKEN="):
                    return line.split("=", 1)[1].strip()

    return "enterprise-rag-dev-token"


def resolve_entity_name(filepath: Path) -> str:
    """Extract entity name from filename or directory.

    Default: use parent directory name as entity (e.g. 'stock reports' → '' ).
    Override by creating a '.entity' file in the demo directory.
    """
    entity_file = filepath.parent / ".entity"
    if entity_file.exists():
        return entity_file.read_text(encoding="utf-8").strip()
    return ""


def get_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def list_documents(api_base: str, headers: dict) -> list[dict]:
    """GET /documents — list all documents."""
    resp = requests.get(f"{api_base}/documents", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upload_file(api_base: str, headers: dict, filepath: Path, entity_name: str) -> dict:
    """POST /documents/upload — upload a file with entity_name."""
    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f)}
        data = {"entity_name": entity_name} if entity_name else {}
        resp = requests.post(
            f"{api_base}/documents/upload",
            headers=headers,
            files=files,
            data=data,
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()


def process_document(api_base: str, headers: dict, doc_id: str) -> dict:
    """POST /documents/{id}/process — trigger processing."""
    resp = requests.post(
        f"{api_base}/documents/{doc_id}/process",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def retry_document(api_base: str, headers: dict, doc_id: str) -> dict:
    """POST /documents/{id}/retry — retry failed processing."""
    resp = requests.post(
        f"{api_base}/documents/{doc_id}/retry",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def wait_for_completion(
    api_base: str, headers: dict, doc_id: str, filename: str
) -> str:
    """Poll document status until completed/failed. Returns final status."""
    start = time.monotonic()
    while time.monotonic() - start < POLL_TIMEOUT:
        resp = requests.get(
            f"{api_base}/documents", headers=headers, timeout=30
        )
        resp.raise_for_status()
        docs = resp.json()
        for doc in docs:
            if doc.get("document_id") == doc_id:
                status = doc.get("status", "")
                if status in ("completed", "failed"):
                    return status
                if status in _PROCESSING_STATUSES:
                    print(f"    {filename}: {status}...", end="\r")
                    time.sleep(POLL_INTERVAL)
                    break
                # Unknown status — treat as terminal
                return status
        else:
            time.sleep(POLL_INTERVAL)
            continue
        time.sleep(POLL_INTERVAL)
    return "timeout"


def process_with_retry(
    api_base: str, headers: dict, doc_id: str, filename: str
) -> str:
    """Process a document, retrying up to MAX_RETRIES times on failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt == 1:
                process_document(api_base, headers, doc_id)
            else:
                print(f"    retry attempt {attempt}/{MAX_RETRIES}...", flush=True)
                retry_document(api_base, headers, doc_id)
        except Exception as e:
            print(f"    trigger failed: {e}")
            continue

        final = wait_for_completion(api_base, headers, doc_id, filename)
        if final == "completed":
            return "completed"
        print(f"    {filename}: {final} (attempt {attempt}/{MAX_RETRIES})")

    return "failed"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Seed demo data")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--token", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--entity", default=None,
                        help="Entity name for all documents (default: from .entity file)")
    args = parser.parse_args()

    demo_dir = resolve_demo_dir(args.data_dir)
    token = resolve_token(args.token)
    headers = get_headers(token)

    # Find demo files
    demo_files = sorted(
        f for f in demo_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not demo_files:
        print(f"No supported files found in {demo_dir}")
        sys.exit(0)

    # Check MinerU availability for PDFs
    pdf_files = [f for f in demo_files if f.suffix.lower() == ".pdf"]
    mineru_token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if pdf_files and not mineru_token:
        # Check .env files
        for env_path in [Path(".env"), Path("../.env"), Path("../../.env")]:
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("MINERU_API_TOKEN="):
                        mineru_token = line.split("=", 1)[1].strip()
                        break
            if mineru_token:
                break

    if pdf_files and not mineru_token:
        non_pdf = [f for f in demo_files if f.suffix.lower() != ".pdf"]
        if not non_pdf:
            print(
                "ERROR: All demo files are PDFs but MINERU_API_TOKEN is not set.\n"
                "PDF demo seeding requires MINERU_API_TOKEN. "
                "Fill .env or use --data-dir with MD/ZIP files.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(f"WARNING: MINERU_API_TOKEN not set, skipping {len(pdf_files)} PDF(s)")
            demo_files = non_pdf

    print(f"Demo directory: {demo_dir}")
    print(f"Files to process: {len(demo_files)}")

    # Resolve entity name
    default_entity = args.entity or resolve_entity_name(demo_files[0])
    if default_entity:
        print(f"Entity: {default_entity}")

    # Check backend health
    try:
        resp = requests.get(
            args.api_base.replace("/api", "/health"), timeout=10
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"ERROR: Backend not reachable at {args.api_base}: {e}",
              file=sys.stderr)
        sys.exit(1)

    # Fetch existing documents for idempotency
    existing_docs = list_documents(args.api_base, headers)
    existing_by_name = {doc["filename"]: doc for doc in existing_docs}

    completed = 0
    skipped = 0
    failed = 0

    for filepath in demo_files:
        filename = filepath.name
        existing = existing_by_name.get(filename)

        # Idempotency check
        if existing:
            status = existing.get("status", "")
            if status == "completed":
                print(f"  [skip] {filename} — already completed")
                skipped += 1
                continue
            elif status in _PROCESSING_STATUSES:
                print(f"  [wait] {filename} — currently {status}")
                final = wait_for_completion(args.api_base, headers,
                                           existing["document_id"], filename)
                if final == "completed":
                    print(f"  [done] {filename} — completed")
                    completed += 1
                else:
                    print(f"  [fail] {filename} — {final}")
                    failed += 1
                continue
            elif status == "uploaded":
                print(f"  [process] {filename} — already uploaded")
                final = process_with_retry(
                    args.api_base, headers,
                    existing["document_id"], filename,
                )
                if final == "completed":
                    print(f"  [done] {filename} — completed")
                    completed += 1
                else:
                    print(f"  [fail] {filename} — {final} after {MAX_RETRIES} retries")
                    failed += 1
                continue
            elif status == "failed":
                # Auto-retry failed documents
                print(f"  [retry] {filename} — previously failed, retrying")
                final = process_with_retry(
                    args.api_base, headers,
                    existing["document_id"], filename,
                )
                if final == "completed":
                    print(f"  [done] {filename} — completed")
                    completed += 1
                else:
                    print(f"  [fail] {filename} — {final} after {MAX_RETRIES} retries")
                    failed += 1
                continue

        # Upload
        entity_name = default_entity
        print(f"  [upload] {filename}...", end=" ", flush=True)
        try:
            doc = upload_file(args.api_base, headers, filepath, entity_name)
            doc_id = doc["document_id"]
            print(f"OK (id={doc_id[:8]}...)")
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1
            continue

        # Process with auto-retry
        print(f"  [process] {filename}...", flush=True)
        final = process_with_retry(args.api_base, headers, doc_id, filename)
        if final == "completed":
            print(f"  [done] {filename} — completed")
            completed += 1
        else:
            print(f"  [fail] {filename} — {final} after {MAX_RETRIES} retries")
            failed += 1

    # Summary
    print()
    print(f"Seed complete: {completed} completed, {skipped} skipped, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
