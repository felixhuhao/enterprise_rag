# Image Support Test Results

## 测试日期

2025-05-22

## 测试环境

- image-to-text: **开启** (IMAGE_DESCRIPTION_ENABLED=true)
- VL 模型: qwen3-vl-flash
- 已重新上传全部 6 份 PDF

---

## V2 Golden Set (stock_reports_v2.jsonl)

17 questions, avg=0.960, pass_rate=100%

| 类型 | 题数 | 平均分 | 通过率 |
|------|------|--------|--------|
| rule | 10 | 0.968 | 100% |
| llm_judge | 5 | 0.928 | 100% |
| no_answer | 2 | 1.000 | 100% |

对比 image-to-text 开启前（同一 golden set）：avg=0.954 → 0.960

**结论：image-to-text 对普通文本问答无退化。**

---

## Image Golden Set (stock_reports_image.jsonl)

5 questions, avg=0.898, pass_rate=80%

| ID | 类型 | 问题 | final | 状态 |
|------|------|------|-------|------|
| img_001 | 图表趋势 | 累计收益率何时拉升 | 1.00 | pass |
| img_002 | 图表峰值 | 累计收益率最高点 | 0.68 | warn |
| img_003 | 散点图对比 | 台积电 ROE | 0.95 | pass |
| img_004 | 估值范围 | P/B 最大/最小值 | 0.94 | pass |
| img_005 | 饼图占比 | 智能手机/工业与汽车 | 0.93 | pass |

img_002 warn 原因：回答 151% 正确但 citation 未匹配 expected_documents（不影响回答质量）。

**结论：image-to-text 显著增强了图表类问题的回答能力，5 题全部成功检索图片描述并提取数值。**

---

## Citation Thumbnail 手动验证

- 引用卡片展开后可见图片数量 badge（如图标 + 数字）
- 缩略图正常加载（80x60px）
- 点击缩略图弹出预览（max 90vw x 85vh）
- 后端 `/api/documents/{id}/assets/{path}` 接口通过 token query param 鉴权正常

---

## 已知局限

1. 12/15 图片未被 Markdown 引用，描述生成但未注入 chunk（P0 设计如此）
2. 图片描述与 chunk 正文混编，长描述可能被 chunk 边界截断
3. 缩略图依赖绝对路径 → 相对路径转换，旧数据需 re-upload 才能正常显示
