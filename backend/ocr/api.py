import requests

from app.config import settings
from ocr.utils.consts import API_URL, MODEL_NAME
from ocr.utils.image_utils import file_to_base64


def call_glm_ocr(
        file_input: str,
        return_crop_images: bool = False,
        need_layout_visualization: bool = False,
        start_page_id: int = None,
        end_page_id: int = None,
) -> dict:
    """
    调用智谱 GLM-OCR 版面解析 API

    参数:
        file_input: 本地文件路径（自动 base64 编码）或公开 URL
        return_crop_images: 是否返回裁剪图片信息
        need_layout_visualization: 是否返回版面可视化图片
        start_page_id: PDF 起始页（从 1 开始）
        end_page_id: PDF 结束页

    返回:
        API 完整 JSON 响应 dict，包含 md_results、layout_details、data_info 等字段
    """
    # 判断输入是 URL 还是本地文件
    if file_input.startswith("http://") or file_input.startswith("https://"):
        file_data = file_input
    else:
        # 本地文件 → base64 编码
        file_data = file_to_base64(file_input)

    payload = {
        "model": MODEL_NAME,
        "file": file_data,
    }

    if return_crop_images:
        payload["return_crop_images"] = True
    if need_layout_visualization:
        payload["need_layout_visualization"] = True
    if start_page_id is not None:
        payload["start_page_id"] = start_page_id
    if end_page_id is not None:
        payload["end_page_id"] = end_page_id

    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {settings.ZHIPU_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"GLM-OCR API 调用失败 (HTTP {response.status_code}): {response.text}"
        )

    return response.json()
