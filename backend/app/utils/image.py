"""
图片处理工具

将 Markdown 中的本地图片路径转换为 Base64 data URI，供前端渲染。
提供同步和异步两种接口。
"""

import asyncio
import base64
import mimetypes
import os
import re

# 允许读取图片的安全目录白名单（相对于 backend 工作目录的绝对路径）
_SAFE_DIRS: list[str] | None = None

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}


def _get_safe_dirs() -> list[str]:
    """懒加载安全目录白名单，基于配置的 UPLOAD_DIR 和当前工作目录"""
    global _SAFE_DIRS
    if _SAFE_DIRS is None:
        from app.config import settings
        cwd = os.getcwd()
        _SAFE_DIRS = [
            os.path.realpath(os.path.join(cwd, settings.UPLOAD_DIR)),
            os.path.realpath(os.path.join(cwd, "output")),
        ]
    return _SAFE_DIRS


def _is_safe_image_path(path: str) -> bool:
    """检查路径是否在白名单目录内且为合法图片扩展名"""
    # 检查扩展名
    _, ext = os.path.splitext(path.lower())
    if ext not in _IMAGE_EXTENSIONS:
        return False
    # 解析真实路径，防止 ../../ 穿越
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return any(real.startswith(d + os.sep) or real == d for d in _get_safe_dirs())


def _local_images_to_data_uri_sync(content) -> str:
    """
    将 Markdown 中的本地图片路径转换为 data URI（同步版本）

    参数:
        content: AI 回复内容，可能是字符串或多模态列表格式

    返回:
        处理后的纯文本内容，本地图片路径已替换为 data URI
    """
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        content = "\n".join(parts)
    if not content:
        return ""

    def _replace(match):
        path = match.group(1).strip()
        if _is_safe_image_path(path) and os.path.isfile(path):
            mime = mimetypes.guess_type(path)[0] or "image/png"
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"![图片](data:{mime};base64,{b64})"
        return match.group(0)

    return re.sub(r'!\[.*?\]\((?!data:)(.*?)\)', _replace, content)


async def local_images_to_data_uri(content) -> str:
    """异步包装：将同步文件 I/O 移到线程池中执行"""
    return await asyncio.to_thread(_local_images_to_data_uri_sync, content)
