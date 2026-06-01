from app.rag.chunking.enrichment import (
    _amount_aliases,
    _normalized_amounts,
    build_search_text,
    enrich_chunks,
    extract_keywords,
    extract_structured_tags,
)


def test_extracts_amount_approval_terms_for_training_section():
    content = "## 五、外部培训管理\n单次费用超过10,000元需VP级别审批，超过30,000元需CEO审批。"
    section = "星辰科技年度培训计划 > 五、外部培训管理"

    keywords = extract_keywords(content, section)
    tags = extract_structured_tags(content, section)
    search_text = build_search_text({
        "content": content,
        "section_title": section,
        "keywords": keywords,
        "structured_tags": tags,
    })

    assert "五、外部培训管理" in keywords
    assert "10,000元" in keywords
    assert "VP审批" in keywords
    assert "CEO审批" in keywords
    assert "amount_threshold" in tags
    assert "approval_rule" in tags
    assert "training_budget" in tags
    assert "金额审批阈值" in search_text
    assert "培训费用" in search_text
    assert "10000元" in search_text


def test_training_without_budget_evidence_does_not_add_training_recall_terms():
    content = "所有培训记录统一存入培训管理系统，作为员工晋升和评优的参考依据。"

    tags = extract_structured_tags(content, "年度培训计划 > 培训考核机制")
    search_text = build_search_text({
        "content": content,
        "section_title": "年度培训计划 > 培训考核机制",
        "structured_tags": tags,
    })

    assert "training_budget" not in tags
    assert "培训预算" not in search_text


def test_does_not_add_finance_recall_terms_without_amount_approval_evidence():
    content = "密码必须每90天强制更换，P1事件30分钟内响应。"

    tags = extract_structured_tags(content, "信息安全策略 > 密码策略")
    search_text = build_search_text({
        "content": content,
        "section_title": "信息安全策略 > 密码策略",
        "structured_tags": tags,
    })

    assert "amount_threshold" not in tags
    assert "approval_rule" not in tags
    assert "金额审批阈值" not in search_text
    assert "费用审批门槛" not in search_text


def test_security_incident_recall_terms_cover_device_loss_queries():
    content = "发现安全事件后，须在4小时内报告信息安全团队。P1紧急事件30分钟内响应。"

    tags = extract_structured_tags(content, "信息安全策略 > 安全事件报告")
    search_text = build_search_text({
        "content": content,
        "section_title": "信息安全策略 > 安全事件报告",
        "structured_tags": tags,
    })

    assert "security_incident_rule" in tags
    assert "安全事件报告" in search_text
    assert "电脑丢失" in search_text
    assert "设备丢失" in search_text


def test_amount_threshold_without_approval_keeps_approval_recall_terms_out():
    content = "年度预算总额500万元以上，作为年度规划参考。"

    tags = extract_structured_tags(content, "年度预算")
    search_text = build_search_text({
        "content": content,
        "section_title": "年度预算",
        "structured_tags": tags,
    })

    assert "amount_threshold" in tags
    assert "approval_rule" not in tags
    assert "预算金额" in search_text
    assert "金额阈值" not in search_text
    assert "金额审批阈值" not in search_text
    assert "审批权限" not in search_text


def test_general_profile_skips_enterprise_policy_terms():
    content = "金额超过50万元的付款须额外经CFO审批。"

    enriched = enrich_chunks([{"content": content, "section_title": "付款管理"}], profile="general")[0]

    assert enriched["enrichment_profile"] == "general"
    assert "50万元" in enriched["keywords"]
    assert "CFO审批" not in enriched["keywords"]
    assert enriched["structured_tags"] == []
    assert "金额审批阈值" not in enriched["search_text"]
    assert "审批权限" not in enriched["search_text"]


def test_date_duration_without_action_does_not_trigger_deadline_rule():
    tags = extract_structured_tags("制度有效期90天，P1事件定义见附录。", "信息安全策略")

    assert "deadline_rule" not in tags


def test_extracts_policy_titles_bold_text_and_acronyms():
    content = "依据《供应商管理制度》执行。**P1响应时间**必须满足SLA要求。"

    keywords = extract_keywords(content, "远景能源 > 安全事件")

    assert "供应商管理制度" in keywords
    assert "P1响应时间" in keywords
    assert "SLA" in keywords


def test_enrich_chunks_preserves_source_content_and_returns_copies():
    chunk = {
        "content": "金额超过50万元的付款须额外经CFO审批。",
        "section_title": "供应商管理制度 > 付款管理",
        "file_title": "08_供应商管理制度.md",
    }

    enriched = enrich_chunks([chunk])

    assert enriched[0] is not chunk
    assert enriched[0]["content"] == chunk["content"]
    assert "keywords" not in chunk
    assert "structured_tags" not in chunk
    assert "search_text" not in chunk
    assert "amount_threshold" in enriched[0]["structured_tags"]
    assert "approval_rule" in enriched[0]["structured_tags"]
    assert "供应商付款" in enriched[0]["search_text"]


def test_table_chunk_amount_approval_enrichment():
    content = (
        "| 报销金额 | 审批人 |\n"
        "| --- | --- |\n"
        "| 5,000元以下 | 直属经理 |\n"
        "| 5,000 - 20,000元 | 部门总监 |\n"
        "| 20,000元以上 | 分管VP |"
    )

    tags = extract_structured_tags(content, "费用报销制度 > 报销审批权限")
    search_text = build_search_text({
        "content": content,
        "section_title": "费用报销制度 > 报销审批权限",
        "structured_tags": tags,
    })

    assert "amount_threshold" in tags
    assert "approval_rule" in tags
    assert "reimbursement_rule" in tags
    assert "金额阈值" in search_text
    assert "金额审批阈值" in search_text
    assert "5000-20000元" in search_text


def test_role_approval_terms_prefer_specific_roles():
    content = "直属经理审批，部门经理复核，分管VP批准。"

    keywords = extract_keywords(content, "")

    assert "直属经理审批" in keywords
    assert "部门经理审批" in keywords
    assert "分管VP审批" in keywords
    assert "经理审批" not in keywords
    assert "VP审批" not in keywords


def test_empty_content_and_section_do_not_crash():
    assert extract_keywords("", "") == []
    assert extract_structured_tags("", "") == []
    assert build_search_text({"content": "", "section_title": ""}) == ""
    assert enrich_chunks([]) == []
    assert enrich_chunks([{}])[0]["search_text"] == ""


def test_normalized_amounts_preserve_boundaries_and_ranges():
    text = "3万元、600 元/晚、50万以上、5,000元以下、5,000 - 20,000元以下、3万-5万元"

    assert _normalized_amounts(text) == [
        "3万元",
        "600元/晚",
        "50万以上",
        "5000元以下",
        "5000-20000元以下",
        "3万-5万元",
    ]


def test_amount_aliases_add_wan_form_for_integer_yuan_amounts():
    assert _amount_aliases("超过30,000元需CEO审批，超过10,000元需VP审批。") == ["3万元", "1万元"]
