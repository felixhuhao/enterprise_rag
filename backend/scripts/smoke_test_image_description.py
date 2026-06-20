"""Smoke test the configured image-description (VL) provider against a real image.

Usage:
    IMAGE_DESCRIPTION_PROVIDER=qwen IMAGE_DESCRIPTION_MODEL=qwen3-vl-flash \
        python backend/scripts/smoke_test_image_description.py path/to/image.png

Verifies provider selection, model ID validity, and a non-empty description.
Requires a valid API key for the selected provider (QWEN_API_KEY or ZHIPU_API_KEY).
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.rag.parsing.image_describer import describe_image


def main():
    parser = argparse.ArgumentParser(description="Smoke test the image-description VL provider.")
    parser.add_argument("image", help="Path to a local PNG/JPEG/WebP image.")
    args = parser.parse_args()

    image_path = args.image
    if not Path(image_path).is_file():
        raise SystemExit(f"image not found: {image_path}")

    print(f"image_description_provider={settings.IMAGE_DESCRIPTION_PROVIDER}")
    print(f"image_description_model={settings.IMAGE_DESCRIPTION_MODEL}")

    result = asyncio.run(describe_image(image_path))
    if result.get("status") != "ok":
        raise SystemExit(f"description failed: {result.get('error')}")

    description = result.get("description", "")
    print(f"description ({len(description)} chars):")
    print(description)
    if not description.strip():
        raise SystemExit("description is empty")
    print("\nOK")


if __name__ == "__main__":
    main()
