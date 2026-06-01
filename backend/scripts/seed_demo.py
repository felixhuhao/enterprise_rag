"""Seed demo data: upload Markdown demo corpus and process them.

Usage:
    python scripts/seed_demo.py [--api-base URL] [--token TOKEN] [--data-dir PATH]

Entity assignment (per file):
    1. Filename prefix: "远景能源_01_差旅.md" → entity = "远景能源"
    2. Fallback: .entity file in demo directory → default for all files
    3. --entity CLI flag overrides both.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_API_BASE = "http://localhost:8010/api"
POLL_INTERVAL = 5
POLL_TIMEOUT = 600
MAX_RETRIES = 2

_DEMO_DIR_CANDIDATES = [
    "/app/data/enterprise_docs",     # Docker
    "../data/enterprise_docs",        # cd backend && python scripts/seed_demo.py
    "data/enterprise_docs",           # from project root
]

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".zip"}

_PROCESSING_STATUSES = (
    "processing", "parsing", "normalizing", "chunking", "embedding", "saving",
)

# Filename entity prefix pattern: "远景能源_01_xxx.md" → entity="远景能源"
_ENTITY_PREFIX_RE = re.compile(r"^([^\d_]+)_\d")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_demo_dir(arg_dir: str | None) -> Path:
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

    print("ERROR: Cannot find demo data directory.", file=sys.stderr)
    sys.exit(1)


def default_entity(dir_path: Path) -> str:
    entity_file = dir_path / ".entity"
    if entity_file.is_file():
        return entity_file.read_text(encoding="utf-8").strip()
    return ""


def entity_for_file(filepath: Path, fallback: str) -> str:
    """Extract entity from filename prefix, e.g. '远景能源_01_xxx.md' → '远景能源'."""
    m = _ENTITY_PREFIX_RE.match(filepath.name)
    if m:
        return m.group(1).strip()
    return fallback


def resolve_token(arg_token: str | None) -> str:
    if arg_token:
        return arg_token
    for env_path in [Path(".env"), Path("../.env"), Path("../../.env")]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("API_TOKEN="):
                    return line.split("=", 1)[1].strip()
    raise SystemExit("--token or API_TOKEN in .env is required")


def get_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def list_documents(api_base: str, headers: dict) -> list[dict]:
    resp = requests.get(f"{api_base}/documents", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def upload_file(api_base: str, headers: dict, filepath: Path, entity_name: str) -> dict:
    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f)}
        data = {"entity_name": entity_name} if entity_name else {}
        resp = requests.post(
            f"{api_base}/documents/upload",
            headers=headers, files=files, data=data, timeout=60,
        )
    resp.raise_for_status()
    return resp.json()


def process_document(api_base: str, headers: dict, doc_id: str) -> dict:
    resp = requests.post(f"{api_base}/documents/{doc_id}/process",
                         headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def retry_document(api_base: str, headers: dict, doc_id: str) -> dict:
    resp = requests.post(f"{api_base}/documents/{doc_id}/retry",
                         headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def wait_for_completion(api_base: str, headers: dict, doc_id: str, filename: str) -> str:
    start = time.monotonic()
    while time.monotonic() - start < POLL_TIMEOUT:
        resp = requests.get(f"{api_base}/documents", headers=headers, timeout=30)
        resp.raise_for_status()
        for doc in resp.json():
            if doc.get("document_id") == doc_id:
                status = doc.get("status", "")
                if status in ("completed", "failed"):
                    return status
                if status in _PROCESSING_STATUSES:
                    print(f"    {filename}: {status}...", end="\r")
                    time.sleep(POLL_INTERVAL)
                    break
        else:
            time.sleep(POLL_INTERVAL)
            continue
        time.sleep(POLL_INTERVAL)
    return "timeout"


def process_with_retry(api_base: str, headers: dict, doc_id: str, filename: str) -> str:
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
                        help="Entity name for all documents (overrides filename prefix and .entity)")
    args = parser.parse_args()

    demo_dir = resolve_demo_dir(args.data_dir)
    token = resolve_token(args.token)
    headers = get_headers(token)

    demo_files = sorted(
        f for f in demo_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not demo_files:
        print(f"No supported files found in {demo_dir}")
        sys.exit(0)

    dir_default_entity = default_entity(demo_dir)
    override_entity = args.entity

    print(f"Demo directory: {demo_dir}")
    print(f"Files to process: {len(demo_files)}")
    if override_entity:
        print(f"Entity (--entity): {override_entity}")
    elif dir_default_entity:
        print(f"Entity default (.entity): {dir_default_entity}")

    # Check backend
    try:
        resp = requests.get(args.api_base.replace("/api", "/health"), timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"ERROR: Backend not reachable: {e}", file=sys.stderr)
        sys.exit(1)

    existing_docs = list_documents(args.api_base, headers)
    existing_by_name = {doc["filename"]: doc for doc in existing_docs}

    completed = 0
    skipped = 0
    failed = 0

    for filepath in demo_files:
        filename = filepath.name
        existing = existing_by_name.get(filename)

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
                final = process_with_retry(args.api_base, headers,
                                          existing["document_id"], filename)
                if final == "completed":
                    print(f"  [done] {filename} — completed")
                    completed += 1
                else:
                    print(f"  [fail] {filename} — failed")
                    failed += 1
                continue
            elif status == "failed":
                print(f"  [retry] {filename} — previously failed, retrying")
                final = process_with_retry(args.api_base, headers,
                                          existing["document_id"], filename)
                if final == "completed":
                    print(f"  [done] {filename} — completed")
                    completed += 1
                else:
                    print(f"  [fail] {filename} — failed")
                    failed += 1
                continue

        entity_name = override_entity or entity_for_file(filepath, dir_default_entity)
        print(f"  [upload] {filename} ({entity_name or '—'})...", end=" ", flush=True)
        try:
            doc = upload_file(args.api_base, headers, filepath, entity_name)
            doc_id = doc["document_id"]
            print(f"OK (id={doc_id[:8]}...)")
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1
            continue

        print(f"  [process] {filename}...", flush=True)
        final = process_with_retry(args.api_base, headers, doc_id, filename)
        if final == "completed":
            print(f"  [done] {filename} — completed")
            completed += 1
        else:
            print(f"  [fail] {filename} — {final}")
            failed += 1

    print()
    print(f"Seed complete: {completed} completed, {skipped} skipped, {failed} failed")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
