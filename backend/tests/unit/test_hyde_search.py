"""Unit tests for HyDE prompt and output normalization."""

import importlib
import sys
import types

import pytest


@pytest.fixture()
def hyde_module(monkeypatch):
    embedding_stub = types.ModuleType("app.rag.embeddings.dense_embedding")
    embedding_stub.dense_embedding = object()
    monkeypatch.setitem(sys.modules, "app.rag.embeddings.dense_embedding", embedding_stub)

    milvus_stub = types.ModuleType("app.rag.vectorstores.general_milvus")
    milvus_stub.COLLECTION_NAME = "test_collection"
    milvus_stub.available_output_fields = lambda fields: fields
    milvus_stub.client = object()
    monkeypatch.setitem(sys.modules, "app.rag.vectorstores.general_milvus", milvus_stub)

    sys.modules.pop("app.rag.query.hyde_search", None)
    module = importlib.import_module("app.rag.query.hyde_search")
    yield module
    sys.modules.pop("app.rag.query.hyde_search", None)


def test_hyde_prompt_has_shape_contract_and_examples(hyde_module):
    assert "2-3句" in hyde_module.HYDE_PROMPT
    assert "80-160字" in hyde_module.HYDE_PROMPT
    assert "不要标题、编号、解释过程" in hyde_module.HYDE_PROMPT
    assert "保留用户问题中的实体、日期、数字、政策名和关键术语" in hyde_module.HYDE_PROMPT
    assert "不要编造具体数值" in hyde_module.HYDE_PROMPT
    assert "星辰科技项目预算250万需要谁审批？" in hyde_module.HYDE_PROMPT
    assert "电脑丢了应该怎么处理？" in hyde_module.HYDE_PROMPT
    assert "星辰科技和远景能源的差旅餐费标准分别是多少？" in hyde_module.HYDE_PROMPT
    assert "星辰科技的API日调用量上限是多少？" in hyde_module.HYDE_PROMPT


def test_normalize_hyde_text_strips_common_preamble(hyde_module):
    text = "以下是假设性回答：星辰科技项目预算超过200万元需要CEO审批。"

    assert hyde_module.normalize_hyde_text(text) == "星辰科技项目预算超过200万元需要CEO审批。"


def test_normalize_hyde_text_strips_fenced_output_and_nested_preamble(hyde_module):
    text = "```text\n输出：可能的文档内容：API接口规范规定企业用户限流为1000次/分钟。\n```"

    assert hyde_module.normalize_hyde_text(text) == "API接口规范规定企业用户限流为1000次/分钟。"


def test_normalize_hyde_text_preserves_plain_content(hyde_module):
    text = "远景能源差旅制度规定国内差旅每日补贴150元，海外差旅每日补贴50美元。"

    assert hyde_module.normalize_hyde_text(text) == text
