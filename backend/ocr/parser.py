import os
import json
from typing import Optional, List

import fitz
from PIL import Image

from ocr.api import call_glm_ocr
from ocr.utils.image_utils import fetch_image
from ocr.utils.format_utils import layout_details_to_cells, cells_to_markdown


class GlmOcrParser:
    """
    基于智谱 GLM-OCR 的文档解析器

    支持 PDF 和图片文件，调用 GLM-OCR 云端 API 进行版面分析和文字提取，
    输出 Markdown 文本和结构化布局 JSON。
    """

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir

    def parse_file(
            self,
            input_path: str,
            output_dir: str = "",
            return_crop_images: bool = False,
            need_layout_visualization: bool = False,
            start_page_id: int = None,
            end_page_id: int = None,
    ) -> List[dict]:
        """
        解析单个文件（自动识别 PDF 或图片）

        参数:
            input_path: 输入文件路径
            output_dir: 输出目录，默认使用初始化时设置的目录
            return_crop_images: 是否返回裁剪图片信息
            need_layout_visualization: 是否返回版面可视化图片
            start_page_id: PDF 起始页（从 1 开始）
            end_page_id: PDF 结束页

        返回:
            解析结果列表，每页一个 dict，包含：
            - md_content: Markdown 文本
            - layout_info: 布局结构化信息 (cells)
            - md_content_path: 保存的 md 文件路径
            - layout_info_path: 保存的 json 文件路径
        """
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"文件不存在: {input_path}")

        output_dir = output_dir or self.output_dir
        save_dir = os.path.abspath(output_dir)

        filename = os.path.splitext(os.path.basename(input_path))[0]
        os.makedirs(save_dir, exist_ok=True)

        print(f"正在解析: {input_path}")

        # 调用 GLM-OCR API
        api_response = call_glm_ocr(
            file_input=input_path,
            return_crop_images=return_crop_images,
            need_layout_visualization=need_layout_visualization,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
        )

        # 提取返回数据
        md_results = api_response.get("md_results", "")
        layout_details = api_response.get("layout_details", [])
        data_info = api_response.get("data_info", {})
        layout_visualization = api_response.get("layout_visualization", [])

        # 将 layout_details 转为统一的 cells 格式（按页分组）
        pages_cells = layout_details_to_cells(layout_details, data_info)
        api_pages = data_info.get("pages", [])

        total_pages = len(pages_cells)
        results = []

        # 加载原始图像（用于图片裁剪）
        origin_images = self._load_origin_images(input_path, total_pages, data_info)

        for page_idx in range(total_pages):
            page_cells = pages_cells[page_idx]
            origin_image = origin_images[page_idx] if page_idx < len(origin_images) else None
            api_page = api_pages[page_idx] if page_idx < len(api_pages) else {}

            # 生成该页的 Markdown
            if page_cells:
                page_md = cells_to_markdown(
                    origin_image, page_cells,
                    api_page_width=api_page.get("width", 0),
                    api_page_height=api_page.get("height", 0),
                )
            else:
                # layout_details 为空时回退到 API 返回的 md_results
                page_md = md_results

            # 页面文件名
            if total_pages == 1:
                page_name = filename
            else:
                page_name = f"{filename}_page_{page_idx}"

            # 保存布局 JSON
            layout_info_path = os.path.join(save_dir, f"{page_name}.json")
            with open(layout_info_path, 'w', encoding="utf-8") as w:
                json.dump(page_cells, w, ensure_ascii=False, indent=2)

            # 保存 Markdown
            md_content_path = os.path.join(save_dir, f"{page_name}.md")
            with open(md_content_path, "w", encoding="utf-8") as w:
                w.write(page_md)

            result = {
                "page_no": page_idx,
                "md_content": page_md,
                "layout_info": page_cells,
                "md_content_path": md_content_path,
                "layout_info_path": layout_info_path,
                "file_path": input_path,
            }

            # 如果有布局可视化图片
            if layout_visualization and page_idx < len(layout_visualization):
                result["layout_image_url"] = layout_visualization[page_idx]

            results.append(result)

        # 如果只有单页，也保存一份合并的 md_results
        if md_results:
            combined_md_path = os.path.join(save_dir, f"{filename}_full.md")
            with open(combined_md_path, "w", encoding="utf-8") as w:
                w.write(md_results)

        print(f"解析完成，结果保存到 {save_dir}")
        return results

    def _load_origin_images(self, input_path: str, total_pages: int, data_info: dict) -> list:
        """
        加载原始图像用于裁剪等操作

        对于 PDF，使用 PyMuPDF 按页转为图像
        对于图片，直接加载
        """
        _, file_ext = os.path.splitext(input_path)

        if file_ext == '.pdf':
            images = []
            with fitz.open(input_path) as doc:
                for page in doc:
                    mat = fitz.Matrix(200 / 72, 200 / 72)
                    pm = page.get_pixmap(matrix=mat, alpha=False)
                    images.append(Image.frombytes('RGB', (pm.width, pm.height), pm.samples))
            return images
        else:
            return [fetch_image(input_path)]


def do_parse(
        input_path: str,
        output: str = "./output",
        return_crop_images: bool = False,
        need_layout_visualization: bool = False,
        start_page_id: Optional[int] = None,
        end_page_id: Optional[int] = None,
) -> List[dict]:
    """
    GLM-OCR 文档解析的函数式入口

    参数:
        input_path: 输入 PDF/图片文件路径
        output: 输出目录 (默认: ./output)
        return_crop_images: 是否返回裁剪图片
        need_layout_visualization: 是否返回版面可视化
        start_page_id: PDF 起始页（从 1 开始）
        end_page_id: PDF 结束页

    返回:
        解析结果列表
    """
    parser = GlmOcrParser(output_dir=output)
    return parser.parse_file(
        input_path=input_path,
        output_dir=output,
        return_crop_images=return_crop_images,
        need_layout_visualization=need_layout_visualization,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m ocr.parser <input_path> [output_dir]")
        sys.exit(1)
    results = do_parse(input_path=sys.argv[1])
    for r in results:
        print(f"--- 第 {r['page_no']} 页 ---")
        print(r['md_content'][:200])
        print()
