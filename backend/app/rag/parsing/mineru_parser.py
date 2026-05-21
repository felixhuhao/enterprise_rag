"""MinerU Online Batch API parser.

Calls the MinerU cloud service to parse PDFs into Markdown + images.
Replaces the previous local CLI-based approach.
"""

import io
import logging
import os
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class MinerUParseResult:
    markdown_path: str
    markdown_content: str
    images_dir: str
    layout_json_path: str | None = None
    content_list_path: str | None = None


def parse_pdf_to_markdown(pdf_path: str, output_dir: str) -> MinerUParseResult:
    """Parse PDF with MinerU Online Batch API and return Markdown artifacts."""
    token = settings.MINERU_API_TOKEN
    base_url = settings.MINERU_BASE_URL

    if not token:
        raise RuntimeError("MINERU_API_TOKEN is not configured")
    if not base_url:
        raise RuntimeError("MINERU_BASE_URL is not configured")

    os.makedirs(output_dir, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    pdf_name = os.path.basename(pdf_path)

    # Step 1: get upload URL
    data_id = uuid.uuid4().hex[:12]
    resp = requests.post(
        f"{base_url}/file-urls/batch",
        headers=headers,
        json={
            "files": [{"name": pdf_name, "data_id": data_id}],
            "model_version": settings.MINERU_MODEL_VERSION,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"MinerU get-upload-url failed: HTTP {resp.status_code} - {resp.text[:500]}"
        )
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(
            f"MinerU get-upload-url error: {body.get('msg', body.get('msgCode', 'unknown'))}"
        )

    batch_id = body["data"]["batch_id"]
    upload_url = body["data"]["file_urls"][0]

    # Step 2: upload PDF to signed URL (with Content-Type retry)
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    upload_session = requests.Session()
    upload_session.trust_env = False
    try:
        put_resp = upload_session.put(upload_url, data=pdf_bytes, timeout=settings.MINERU_UPLOAD_TIMEOUT)
        # 首次失败则强制指定 Content-Type 重试
        if put_resp.status_code not in (200, 201):
            logger.warning(
                "MinerU upload first attempt failed (HTTP %d), retrying with Content-Type: application/pdf",
                put_resp.status_code,
            )
            put_resp = upload_session.put(
                upload_url, data=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
                timeout=settings.MINERU_UPLOAD_TIMEOUT,
            )
            if put_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"MinerU upload failed after retry: HTTP {put_resp.status_code} - {put_resp.text[:500]}"
                )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"MinerU upload network error: {e}") from e
    finally:
        upload_session.close()

    # Step 3: poll for results
    deadline = time.time() + settings.MINERU_POLL_TIMEOUT
    zip_url = None
    while time.time() < deadline:
        poll_resp = requests.get(
            f"{base_url}/extract-results/batch/{batch_id}",
            headers=headers,
            timeout=30,
        )
        if poll_resp.status_code != 200:
            time.sleep(settings.MINERU_POLL_INTERVAL)
            continue

        poll_body = poll_resp.json()
        extract_result = (poll_body.get("data") or {}).get("extract_result", [])
        if not extract_result:
            time.sleep(settings.MINERU_POLL_INTERVAL)
            continue

        item = extract_result[0]
        state = item.get("state", "")

        if state == "done":
            zip_url = item.get("full_zip_url")
            if not zip_url:
                raise RuntimeError("MinerU returned 'done' but no full_zip_url")
            break
        elif state in ("failed", "error"):
            err_msg = item.get("err_msg", "unknown error")
            raise RuntimeError(f"MinerU extraction failed: {err_msg}")

        time.sleep(settings.MINERU_POLL_INTERVAL)

    if zip_url is None:
        raise RuntimeError(
            f"MinerU polling timed out after {settings.MINERU_POLL_TIMEOUT}s"
        )

    # Step 4: download ZIP and extract
    zip_resp = requests.get(zip_url, timeout=settings.MINERU_DOWNLOAD_TIMEOUT)
    if zip_resp.status_code != 200:
        raise RuntimeError(
            f"MinerU ZIP download failed: HTTP {zip_resp.status_code}"
        )

    zip_path = os.path.join(output_dir, "mineru_result.zip")
    with open(zip_path, "wb") as f:
        f.write(zip_resp.content)

    raw_dir = os.path.join(output_dir, "mineru_raw")
    os.makedirs(raw_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        _safe_extractall(zf, raw_dir)

    # Select markdown by priority: same-name stem > full.md > first .md
    pdf_stem = Path(pdf_name).stem
    selected_md = _select_markdown(raw_dir, pdf_stem)
    if selected_md is None:
        raise RuntimeError("MinerU ZIP contains no markdown file")

    content = selected_md.read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError("MinerU produced empty markdown")

    canonical_md = Path(output_dir) / "document.md"
    canonical_md.write_text(content, encoding="utf-8")

    return collect_mineru_result(output_dir)


def _select_markdown(raw_dir: str, pdf_stem: str) -> Path | None:
    """Select the best markdown file from extracted MinerU output."""
    root = Path(raw_dir)
    all_md = [p for p in root.rglob("*.md") if p.is_file()]
    if not all_md:
        return None

    # Priority: same-name stem > full.md > first found
    for md in all_md:
        if md.stem.lower() == pdf_stem.lower():
            return md
    for md in all_md:
        if md.name.lower() == "full.md":
            return md
    return all_md[0]


def collect_mineru_result(output_dir: str) -> MinerUParseResult:
    """Collect Markdown and optional MinerU artifacts from output directory."""
    root = Path(output_dir)
    md_candidates = sorted(
        [p for p in root.rglob("*.md") if p.is_file()],
        key=lambda p: (0 if p.name.lower() in {"full.md", "document.md"} else 1, len(str(p))),
    )
    if not md_candidates:
        raise RuntimeError("MinerU did not produce Markdown")

    markdown_path = md_candidates[0]
    content = markdown_path.read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError("MinerU produced empty Markdown")

    canonical_md = root / "document.md"
    if markdown_path.resolve() != canonical_md.resolve():
        canonical_md.write_text(content, encoding="utf-8")
        markdown_path = canonical_md

    images_dir = _find_first_dir(root, "images") or str(root / "images")
    os.makedirs(images_dir, exist_ok=True)

    return MinerUParseResult(
        markdown_path=str(markdown_path),
        markdown_content=content,
        images_dir=images_dir,
        layout_json_path=_find_first_file(root, "layout.json"),
        content_list_path=_find_first_file(root, "content_list.json"),
    )


def _find_first_file(root: Path, name: str) -> str | None:
    stem = Path(name).stem
    for path in root.rglob(f"*{stem}*"):
        if path.is_file() and path.name.endswith(Path(name).suffix):
            return str(path)
    return None


def _find_first_dir(root: Path, name: str) -> str | None:
    for path in root.rglob(name):
        if path.is_dir():
            return str(path)
    return None


def _safe_extractall(zf: zipfile.ZipFile, dest: str):
    """extractall with zip-slip protection: reject entries escaping dest."""
    dest_path = os.path.realpath(dest)
    for info in zf.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if not target.startswith(dest_path + os.sep) and target != dest_path:
            raise RuntimeError(
                f"zip-slip detected: '{info.filename}' escapes target directory"
            )
    zf.extractall(dest)
