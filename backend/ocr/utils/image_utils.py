import os
import base64
import copy
from io import BytesIO

import requests
from PIL import Image


# 文件扩展名 -> MIME 类型映射
_EXT_TO_MIME = {
    '.pdf': 'application/pdf',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
}


def PILimage_to_base64(image, format='PNG'):
    """PIL Image 转 base64 data URI 字符串"""
    buffered = BytesIO()
    image.save(buffered, format=format)
    base64_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f"data:image/{format.lower()};base64,{base64_str}"


def file_to_base64(file_path):
    """本地文件路径转带 data URI 前缀的 base64 字符串"""
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    mime = _EXT_TO_MIME.get(ext, 'application/octet-stream')
    with open(file_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    return f"data:{mime};base64,{b64}"


def to_rgb(pil_image: Image.Image) -> Image.Image:
    """将图像转换为 RGB 模式"""
    if pil_image.mode == 'RGBA':
        white_background = Image.new("RGB", pil_image.size, (255, 255, 255))
        white_background.paste(pil_image, mask=pil_image.split()[3])
        return white_background
    else:
        return pil_image.convert("RGB")


def fetch_image(image) -> Image.Image:
    """
    统一加载图像，支持多种输入格式：
    - PIL.Image 对象
    - http/https URL
    - data:image base64 data URI
    - 本地文件路径
    """
    assert image is not None, f"图像输入无效: {image}"

    image_obj = None
    if isinstance(image, Image.Image):
        image_obj = image
    elif image.startswith("http://") or image.startswith("https://"):
        with requests.get(image, stream=True) as response:
            response.raise_for_status()
            with BytesIO(response.content) as bio:
                image_obj = copy.deepcopy(Image.open(bio))
    elif image.startswith("data:image"):
        if "base64," in image:
            _, base64_data = image.split("base64,", 1)
            data = base64.b64decode(base64_data)
            with BytesIO(data) as bio:
                image_obj = copy.deepcopy(Image.open(bio))
    else:
        image_obj = Image.open(image)

    if image_obj is None:
        raise ValueError(f"无法识别的图像输入: {image}")

    return to_rgb(image_obj)
