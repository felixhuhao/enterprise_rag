"""Shared test fixtures."""

import os
import tempfile

import pytest


@pytest.fixture
def sample_markdown():
    """含多级标题 + Markdown 表格 + HTML 表格的测试 MD。"""
    return """\
# 测试年报

## 公司概况
中芯国际集成电路制造有限公司（以下简称"本公司"或"中芯国际"）。

## 财务数据

### 营收概况
本年度营业收入持续增长。

| 项目 | 2023年 | 2024年 | 2025年 |
|------|--------|--------|--------|
| 营业收入 | 400亿 | 480亿 | 550亿 |
| 净利润 | 60亿 | 80亿 | 100亿 |
| 毛利率 | 22% | 25% | 28% |

### 资产负债表

<table>
<tr><th>项目</th><th>期末余额</th><th>期初余额</th></tr>
<tr><td>总资产</td><td>3000亿</td><td>2800亿</td></tr>
<tr><td>总负债</td><td>1200亿</td><td>1100亿</td></tr>
</table>

## 总结
公司整体财务状况良好。
"""


@pytest.fixture
def tmp_parsed_dir(tmp_path):
    """临时 parsed 目录。"""
    d = tmp_path / "parsed"
    d.mkdir()
    return str(d)


@pytest.fixture
def small_table_md():
    """小表格（<=2000 tokens）。"""
    return """\
## 小表测试

| 指标 | 值 |
|------|-----|
| 营收 | 100亿 |
"""


@pytest.fixture
def large_table_md():
    """大表格（>2000 tokens），需要行组切分。"""
    header = "| 指标 | Q1 | Q2 | Q3 | Q4 |"
    sep = "|------|-----|-----|-----|-----|"
    rows = [f"| 项目{i:03d} | {i*10} | {i*20} | {i*30} | {i*40} |" for i in range(100)]
    return f"## 大表测试\n\n{header}\n{sep}\n" + "\n".join(rows)


def pytest_collection_modifyitems(config, items):
    """自动跳过需要外部服务的测试。"""
    skip_milvus = pytest.mark.skip(reason="需要本地 Milvus (设置 MILVUS_URI)")
    skip_mineru = pytest.mark.skip(reason="需要 RUN_MINERU_E2E=1")

    for item in items:
        if "milvus" in item.keywords and not os.environ.get("MILVUS_URI"):
            item.add_marker(skip_milvus)
        if "mineru" in item.keywords and not os.environ.get("RUN_MINERU_E2E"):
            item.add_marker(skip_mineru)
