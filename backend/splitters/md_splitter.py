import base64
import hashlib
import io
import os
import re
from typing import List, Tuple

from PIL import Image
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from utils.common_utils import get_sorted_md_files


class MarkdownDirSplitter:
    """将 OCR 产出的 Markdown 文件分割为图文绑定的 Document 列表"""

    def __init__(self, images_output_dir: str, text_chunk_size: int = 1000):
        self.images_output_dir = images_output_dir
        self.text_chunk_size = text_chunk_size
        os.makedirs(self.images_output_dir, exist_ok=True)

        self.header_splitter = MarkdownHeaderTextSplitter([
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ])

        self.char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.text_chunk_size,
            chunk_overlap=100,
            separators=["\n\n", "\n"],
        )

    def process_md_dir(self, md_dir: str, source_filename: str) -> List[Document]:
        """处理整个 MD 目录，返回图文绑定的 Document 列表"""
        md_files = get_sorted_md_files(md_dir)
        # 排除 _full.md，它是 parser 的合并产物，内容与分页文件重复
        md_files = [f for f in md_files if not os.path.basename(f).endswith('_full.md')]
        all_docs = []
        for md_file in md_files:
            all_docs.extend(self._process_md_file(md_file))
        return self._fill_title_hierarchy(all_docs, source_filename)

    def _process_md_file(self, md_file: str) -> List[Document]:
        """处理单个 MD 文件：按标题切分 → 提取图片 → 图文绑定"""
        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        raw_chunks = self.header_splitter.split_text(content)
        docs = []

        for chunk in raw_chunks:
            image_data_uris, image_paths, clean_text = self._extract_images(chunk.page_content)
            page_content = clean_text.strip() or ("[图片]" if image_data_uris else "")
            if not page_content and not image_data_uris:
                continue

            chunk.metadata["images"] = image_data_uris      # 用于 embedding（内存中的 base64）
            chunk.metadata["image_paths"] = image_paths      # 用于 Milvus 存储（文件路径）
            docs.append(Document(page_content=page_content, metadata=chunk.metadata))

        return self._split_oversized(docs)

    # ── 图片处理 ──────────────────────────────────────────

    _IMG_TAG_PATTERN = re.compile(r'!\[\]\(data:image/(.*?);base64,(.*?)\)', re.DOTALL)

    def _extract_images(self, text: str) -> Tuple[List[str], List[str], str]:
        """
        提取 base64 图片：同时生成 data URI（用于 embedding）和保存文件（用于存储）

        Returns:
            image_data_uris: base64 data URI 列表
            image_paths: 保存的文件路径列表
            clean_text: 移除图片标签后的文本
        """
        image_data_uris = []
        image_paths = []

        for m in self._IMG_TAG_PATTERN.finditer(text):
            ext = m.group(1).split(";")[0]
            b64 = m.group(2)

            data_uri = f"data:image/{ext};base64,{b64}"
            image_data_uris.append(data_uri)

            # 保存到磁盘
            ext = ext if ext in ("png", "jpg", "jpeg") else "png"
            name = hashlib.md5(b64.encode()).hexdigest()
            path = os.path.join(self.images_output_dir, f"{name}.{ext}")
            self._save_image(b64, path)
            image_paths.append(path)

        clean_text = self._IMG_TAG_PATTERN.sub("", text)
        return image_data_uris, image_paths, clean_text

    @staticmethod
    def _save_image(b64_data: str, path: str):
        """base64 → 保存为图片文件"""
        if b64_data.startswith("data:image/"):
            b64_data = b64_data.split("base64,", 1)[1]
        img = Image.open(io.BytesIO(base64.b64decode(b64_data)))
        img.save(path)

    # ── 超长文本二次切分 ────────────────────────────────────

    def _split_oversized(self, docs: List[Document]) -> List[Document]:
        """对超过 chunk_size 的文档进行字符级二次切分，继承父级图片信息"""
        result = []
        for doc in docs:
            if len(doc.page_content) <= self.text_chunk_size:
                result.append(doc)
                continue
            parent_images = doc.metadata.get("images", [])
            parent_paths = doc.metadata.get("image_paths", [])
            for sub in self.char_splitter.split_documents([doc]):
                sub.metadata["images"] = parent_images
                sub.metadata["image_paths"] = parent_paths
                result.append(sub)
        return result

    # ── 标题层级补齐 ──────────────────────────────────────

    def _fill_title_hierarchy(self, docs: List[Document], source_filename: str) -> List[Document]:
        """为每个 Document 补齐缺失的上级标题，并设置 source"""
        state = {1: "", 2: "", 3: ""}
        result = []

        for doc in docs:
            meta = doc.metadata.copy()
            meta["source"] = source_filename

            for level in range(1, 4):
                key = f"Header {level}"
                if meta.get(key):
                    state[level] = meta[key]
                    for lower in range(level + 1, 4):
                        state[lower] = ""

            for level in range(1, 4):
                key = f"Header {level}"
                if not meta.get(key):
                    meta[key] = state[level]

            result.append(Document(page_content=doc.page_content, metadata=meta))
        return result


if __name__ == "__main__":
    md_dir = r"D:\CodeProjects\multimodel_rag\output\第一章 Apache Flink 概述"
    splitter = MarkdownDirSplitter(images_output_dir=r"D:\CodeProjects\multimodel_rag\output\images")
    docs = splitter.process_md_dir(md_dir, "第一章 Apache Flink 概述.pdf")

    for i, doc in enumerate(docs):
        imgs = doc.metadata.get("images", [])
        paths = doc.metadata.get("image_paths", [])
        tag = f", 图片×{len(imgs)}" if imgs else ""
        print(f"#{i + 1}{tag}: {doc.page_content[:60]}...")
        if paths:
            print(f"   paths: {paths}")
