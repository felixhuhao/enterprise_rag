# GLM-OCR API
API_URL = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
MODEL_NAME = "glm-ocr"

# 文件大小限制
MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10MB
MAX_PDF_SIZE = 50 * 1024 * 1024     # 50MB
MAX_PDF_PAGES = 100

# 支持的图片扩展名
image_extensions = {'.jpg', '.jpeg', '.png'}

# GLM-OCR label -> 统一 category 映射
LABEL_TO_CATEGORY = {
    "image": "Picture",
    "formula": "Formula",
    "table": "Table",
    "title": "Title",
    "text": "Text",
    "header": "Page-header",
    "footer": "Page-footer",
    "reference": "Footnote",
    "page_number": "Text",
    "seal": "Picture",
}
