"""Image-to-text description via VL model (Qwen-VL series).

Scans images directory, calls VL API for descriptions, caches to descriptions.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import base64
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

VL_PROMPT = """\
请用中文详细描述这张图片的内容。

如果是图表（折线图/柱状图/饼图等），请描述数据趋势和关键数值。
如果是流程图/架构图，请描述结构关系和关键组件。
如果是截图/照片，请描述主要内容和关键信息。
请输出结构化的文字描述，200-500字。"""


def _encode_image_base64(image_path: str) -> str:
    """Read image file and return base64 encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_image_mime_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


async def describe_image(image_path: str) -> dict:
    """Describe a single image using VL model.

    Returns {"description": str, "status": "ok"} or {"status": "failed", "error": str}.
    """
    model = settings.IMAGE_DESCRIPTION_MODEL
    api_key = settings.ZHIPU_API_KEY
    base_url = settings.ZHIPU_BASE_URL
    timeout = settings.IMAGE_DESCRIPTION_TIMEOUT

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        b64 = _encode_image_base64(image_path)
        mime = _get_image_mime_type(image_path)

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": VL_PROMPT},
                    ],
                }
            ],
            max_tokens=settings.IMAGE_DESCRIPTION_MAX_TOKENS,
            timeout=timeout,
        )
        description = response.choices[0].message.content.strip()
        return {"description": description, "status": "ok"}

    except Exception as e:
        logger.warning("Failed to describe image %s: %s", image_path, e)
        return {"status": "failed", "error": str(e)}


def _scan_images(images_dir: str) -> list[str]:
    """Scan directory for supported image files."""
    paths = []
    for name in sorted(os.listdir(images_dir)):
        if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
            full_path = os.path.join(images_dir, name)
            if os.path.getsize(full_path) <= settings.IMAGE_DESCRIPTION_MAX_SIZE_MB * 1024 * 1024:
                paths.append(full_path)
            else:
                logger.info("Skipping large image: %s", name)
    return paths


def _load_cache(images_dir: str) -> dict[str, dict]:
    """Load existing descriptions.json cache."""
    cache_path = os.path.join(images_dir, "descriptions.json")
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read descriptions cache: %s", e)
    return {}


def _save_cache(images_dir: str, cache: dict[str, dict]):
    """Save descriptions.json cache."""
    cache_path = os.path.join(images_dir, "descriptions.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def batch_describe_images(images_dir: str) -> dict[str, dict]:
    """Describe all images in directory, using cache for already-processed ones.

    Returns dict keyed by relative path (e.g. "images/foo.jpg") -> {description, image_path, status}.
    """
    cache = _load_cache(images_dir)
    image_paths = _scan_images(images_dir)

    if not image_paths:
        return cache

    # Filter out already-described images
    to_describe = []
    for img_path in image_paths:
        rel_key = os.path.relpath(img_path, os.path.dirname(images_dir)).replace(os.sep, "/")
        if rel_key not in cache or cache[rel_key].get("status") != "ok":
            to_describe.append((img_path, rel_key))

    if to_describe:
        concurrency = settings.IMAGE_DESCRIPTION_CONCURRENCY
        semaphore = asyncio.Semaphore(concurrency)

        async def _describe_with_semaphore(img_path, rel_key):
            async with semaphore:
                result = await describe_image(img_path)
                result["image_path"] = img_path
                return rel_key, result

        async def _run_batch():
            tasks = [_describe_with_semaphore(p, k) for p, k in to_describe]
            return await asyncio.gather(*tasks, return_exceptions=True)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                results = pool.submit(asyncio.run, _run_batch()).result()
        else:
            results = asyncio.run(_run_batch())

        for item in results:
            if isinstance(item, BaseException):
                if not isinstance(item, Exception):
                    raise item
                logger.warning("Batch describe error: %s", item)
                continue
            rel_key, result = item
            cache[rel_key] = result

        _save_cache(images_dir, cache)

    return cache
