import re
from typing import List, Dict

from PIL import Image

from ocr.utils.consts import LABEL_TO_CATEGORY
from ocr.utils.image_utils import PILimage_to_base64


def normalize_bbox_to_pixels(bbox_2d: list, width: int, height: int) -> list:
    """
    将 GLM-OCR 返回的 bbox 转为像素坐标。

    GLM-OCR 对不同 PDF 可能返回不同格式的坐标：
    - 归一化坐标 [0, 1]：需要乘以页面宽高
    - 已是像素坐标（值 > 1）：直接使用
    """
    max_val = max(abs(v) for v in bbox_2d)
    if max_val <= 1:
        return [
            int(bbox_2d[0] * width),
            int(bbox_2d[1] * height),
            int(bbox_2d[2] * width),
            int(bbox_2d[3] * height),
        ]
    else:
        return [int(v) for v in bbox_2d]


def layout_details_to_cells(layout_details: list, data_info: dict) -> List[List[Dict]]:
    """
    将 GLM-OCR 的 layout_details 转为统一 cells 格式
    返回按页分组的列表: [[{bbox, category, text}, ...], ...]

    GLM-OCR layout_details 是二维数组: [page0_cells, page1_cells, ...]
    每个 cell: {index, label, bbox_2d, content, height, width}
    """
    pages = data_info.get("pages", [])
    all_pages_cells = []

    for page_idx, page_items in enumerate(layout_details):
        page_info = pages[page_idx] if page_idx < len(pages) else {}
        page_width = page_info.get("width", 1)
        page_height = page_info.get("height", 1)

        cells = []
        for item in page_items:
            label = item.get("label", "text")
            category = LABEL_TO_CATEGORY.get(label, "Text")
            bbox_2d = item.get("bbox_2d", [0, 0, 0, 0])
            bbox = normalize_bbox_to_pixels(bbox_2d, page_width, page_height)
            content = item.get("content", "")

            cells.append({
                "bbox": bbox,
                "category": category,
                "text": content,
            })

        all_pages_cells.append(cells)

    return all_pages_cells


def get_formula_in_markdown(text: str) -> str:
    """将公式文本格式化为标准 Markdown 数学块"""
    if not text:
        return ""

    text = text.strip()

    if text.startswith('$$') and text.endswith('$$'):
        inner = text[2:-2].strip()
        if '$' not in inner:
            return f"$$\n{inner}\n$$"
        return text

    if text.startswith('\\[') and text.endswith('\\]'):
        inner = text[2:-2].strip()
        return f"$$\n{inner}\n$$"

    if not _has_latex(text):
        return text

    if text[0] == '`' and text[-1] == '`':
        text = text[1:-1]

    return f"$$\n{text}\n$$"


def _has_latex(text: str) -> bool:
    """检查文本是否包含 LaTeX 标记"""
    patterns = [
        r'\$\$.*?\$\$',
        r'\$[^$\n]+?\$',
        r'\\begin\{.*?\}.*?\\end\{.*?\}',
        r'\\[a-zA-Z]+\{.*?\}',
        r'\\[a-zA-Z]+',
    ]
    return any(re.search(p, text, re.DOTALL) for p in patterns)


def cells_to_markdown(image: Image.Image, cells: List[Dict],
                     api_page_width: int = 0, api_page_height: int = 0,
                     no_page_hf: bool = False) -> str:
    """
    将 cells 列表转为 Markdown 文本

    - Picture: 裁剪图片区域，嵌入 base64
    - Formula: 格式化为 LaTeX 数学块
    - Table: 保持 HTML 格式
    - 其他: 直接输出文本

    Args:
        image: 渲染后的页面图像
        cells: cell 列表（bbox 为 API 页面坐标系）
        api_page_width: API 返回的页面宽度（用于坐标映射）
        api_page_height: API 返回的页面高度（用于坐标映射）
    """
    text_items = []
    img_w, img_h = image.size if image else (0, 0)
    # 坐标映射比例：API 页面坐标 → 渲染图像坐标
    scale_x = img_w / api_page_width if api_page_width else 1
    scale_y = img_h / api_page_height if api_page_height else 1

    for cell in cells:
        x1, y1, x2, y2 = cell['bbox']
        text = cell.get('text', '')
        category = cell.get('category', 'Text')

        if no_page_hf and category in ('Page-header', 'Page-footer'):
            continue

        if category == 'Picture':
            if image is not None:
                try:
                    # 映射到渲染图像坐标
                    rx1 = int(x1 * scale_x)
                    ry1 = int(y1 * scale_y)
                    rx2 = int(x2 * scale_x)
                    ry2 = int(y2 * scale_y)
                    crop = image.crop((rx1, ry1, rx2, ry2))
                    text_items.append(f"![]({PILimage_to_base64(crop)})")
                except Exception:
                    pass
        elif category == 'Formula':
            text_items.append(get_formula_in_markdown(text))
        else:
            text = text.strip() if text else ""
            if text:
                text_items.append(text)

    return '\n\n'.join(text_items)


def fix_streamlit_formulas(md: str) -> str:
    """修复 Markdown 中公式格式，确保在 Streamlit 中正确显示"""
    def replace_formula(match):
        content = match.group(1)
        if content.startswith('\n'):
            content = content[1:]
        if content.endswith('\n'):
            content = content[:-1]
        return f'$$\n{content}\n$$'

    return re.sub(r'\$\$(.*?)\$\$', replace_formula, md, flags=re.DOTALL)
