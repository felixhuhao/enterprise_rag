"""Rule-based chunk search enrichment.

The generated fields are retrieval metadata only. Source ``content`` must stay
unchanged because rerank, prompts, and citations should continue to use it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from app.rag.chunking.structured_tag_registry import normalize_structured_tags

MAX_KEYWORDS = 8

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*([^*\n]{2,80})\*\*")
_BOOK_TITLE_RE = re.compile(r"《([^》]{2,80})》")
_ACRONYM_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,12}(?![A-Za-z0-9])")
_POLICY_PHRASE_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9_（）()·\-]{2,32}"
    r"(?:办法|制度|流程|规范|标准|政策|指南|规定|条例|计划|手册)"
)
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_BOUNDARY = r"(?:以上|以下|以内|不低于|不超过|起|封顶)?"
_AMOUNT_RE = re.compile(
    rf"{_NUM}\s*(?:万)?\s*(?:-|－|—|–|~|至|到)\s*{_NUM}\s*(?:万|千)?\s*元(?:/[^\s，。；、|]+)?{_BOUNDARY}"
    rf"|{_NUM}\s*(?:万|千)?\s*元(?:/[^\s，。；、|]+)?{_BOUNDARY}"
    rf"|{_NUM}\s*万(?:元)?{_BOUNDARY}"
)
_DATE_TIME_RE = re.compile(r"\d+\s*(?:个)?(?:工作日|自然日|小时|分钟|天|日|周|月|年)")

_THRESHOLD_WORDS = ("超过", "以下", "以上", "以内", "低于", "高于", "不低于", "不超过", "大于", "小于")
_APPROVAL_WORDS = ("审批", "批准", "签字", "审核", "复核")
_ROLES = (
    "CEO",
    "CFO",
    "CTO",
    "VP",
    "分管VP",
    "总经理",
    "技术总监",
    "采购部总监",
    "部门总监",
    "直属经理",
    "部门经理",
    "审批人",
    "负责人",
    "主管",
    "经理",
)


def extract_keywords(content: str, section_title: str = "", profile: str = "enterprise_policy") -> list[str]:
    """Extract deterministic searchable keywords from one chunk."""
    profile = _normalize_profile(profile)
    text = _clean_text(content)
    candidates: list[str] = []

    candidates.extend(_section_keywords(section_title))
    candidates.extend(_HEADING_RE.findall(content or ""))
    candidates.extend(_BOLD_RE.findall(content or ""))
    candidates.extend(_BOOK_TITLE_RE.findall(content or ""))
    candidates.extend(_POLICY_PHRASE_RE.findall(text))
    candidates.extend(_ACRONYM_RE.findall(text))
    candidates.extend(_AMOUNT_RE.findall(text))
    if profile == "enterprise_policy":
        candidates.extend(_role_approval_terms(text))

    return _dedupe(_clean_keyword(item) for item in candidates)[:MAX_KEYWORDS]


def extract_structured_tags(content: str, section_title: str = "", profile: str = "enterprise_policy") -> list[str]:
    """Return coarse structured tags used to build search_text."""
    profile = _normalize_profile(profile)
    if profile != "enterprise_policy":
        return []

    text = f"{section_title}\n{content or ''}"
    tags: list[str] = []

    has_amount = bool(_AMOUNT_RE.search(text))
    has_threshold = any(word in text for word in _THRESHOLD_WORDS)
    has_approval = any(word in text for word in _APPROVAL_WORDS)

    if has_amount and has_threshold:
        tags.append("amount_threshold")
    if has_approval:
        tags.append("approval_rule")
    if "培训" in text and any(word in text for word in ("预算", "费用", "金额", "报销", "审批")):
        tags.append("training_budget")
    if "付款" in text or "支付" in text:
        tags.append("payment_rule")
    if "报销" in text:
        tags.append("reimbursement_rule")
    if "采购" in text or "供应商" in text:
        tags.append("procurement_rule")
    if "预算" in text:
        tags.append("budget_rule")
    if _DATE_TIME_RE.search(text) and any(word in text for word in ("提交", "报告", "响应", "处理", "申请")):
        tags.append("deadline_rule")
    if _has_security_incident_evidence(text):
        tags.append("security_incident_rule")

    return normalize_structured_tags(_dedupe(tags), profile=profile)


def build_search_text(chunk: Mapping[str, object], profile: str = "enterprise_policy") -> str:
    """Build enriched sparse/BM25 text without changing source content."""
    profile = _normalize_profile(profile)
    content = str(chunk.get("content") or "")
    section_title = str(chunk.get("section_title") or "")
    file_title = str(chunk.get("file_title") or "")
    entity_name = str(chunk.get("entity_name") or "")
    table_title = str(chunk.get("table_title") or "")
    keywords = list(chunk.get("keywords") or extract_keywords(content, section_title, profile=profile))
    tags = normalize_structured_tags(
        chunk.get("structured_tags") or extract_structured_tags(content, section_title, profile=profile),
        profile=profile,
    )

    pieces = [
        entity_name,
        file_title,
        section_title,
        table_title,
        content,
        " ".join(str(item) for item in keywords),
        " ".join(str(item) for item in tags),
        " ".join(_normalized_amounts(content)),
        " ".join(_amount_aliases(content)),
        " ".join(_recall_terms(tags)) if profile == "enterprise_policy" else "",
    ]
    return _clean_text(" ".join(piece for piece in pieces if piece))


def enrich_chunks(chunks: list[dict], profile: str = "enterprise_policy") -> list[dict]:
    """Return copies of chunks with keywords, structured_tags, and search_text."""
    profile = _normalize_profile(profile)
    if profile == "none":
        return [dict(chunk) for chunk in chunks]

    enriched: list[dict] = []
    for chunk in chunks:
        row = dict(chunk)
        content = str(row.get("content") or "")
        section_title = str(row.get("section_title") or "")
        row["enrichment_profile"] = profile
        row["keywords"] = extract_keywords(content, section_title, profile=profile)
        row["structured_tags"] = extract_structured_tags(content, section_title, profile=profile)
        row["search_text"] = build_search_text(row, profile=profile)
        enriched.append(row)
    return enriched


def _normalize_profile(profile: str) -> str:
    if profile in {"none", "general", "enterprise_policy"}:
        return profile
    return "enterprise_policy"


def _recall_terms(tags: list[str]) -> list[str]:
    terms: list[str] = []
    tag_set = set(tags)
    has_approval = "approval_rule" in tag_set
    if {"amount_threshold", "approval_rule"}.issubset(tag_set):
        terms.extend([
            "金额阈值",
            "费用标准",
            "金额上限",
            "金额下限",
            "金额范围",
            "费用门槛",
            "金额审批阈值",
            "费用审批门槛",
            "超过金额审批",
            "审批权限",
            "审批标准",
            "金额审批",
            "费用审批",
        ])
    if "payment_rule" in tag_set:
        terms.extend(["付款金额", "支付金额"])
        if has_approval:
            terms.extend(["付款审批", "支付审批"])
    if "budget_rule" in tag_set:
        terms.extend(["预算金额"])
        if has_approval:
            terms.append("预算审批")
    if "reimbursement_rule" in tag_set:
        terms.extend(["报销金额", "费用标准"])
        if has_approval:
            terms.append("报销审批")
    if "procurement_rule" in tag_set:
        terms.append("供应商金额")
        if has_approval:
            terms.extend(["采购审批", "供应商付款"])
    if "training_budget" in tag_set:
        terms.extend(["培训费用", "外部培训", "培训预算"])
    if "deadline_rule" in tag_set:
        terms.extend(["时限", "截止时间", "提交时限", "报告时限", "响应时间"])
    if "security_incident_rule" in tag_set:
        terms.extend([
            "安全事件",
            "信息安全事件",
            "安全事件报告",
            "信息安全报告",
            "安全事件响应",
            "数据泄露",
            "设备丢失",
            "电脑丢失",
            "笔记本丢失",
            "终端丢失",
            "资产丢失",
        ])
    return _dedupe(terms)


def _section_keywords(section_title: str) -> list[str]:
    parts = [part.strip() for part in str(section_title or "").split(">")]
    return [part for part in parts if part]


def _role_approval_terms(text: str) -> list[str]:
    if not any(word in text for word in _APPROVAL_WORDS):
        return []
    matched: list[str] = []
    for role in sorted(_ROLES, key=len, reverse=True):
        if role in text:
            if any(role in existing for existing in matched):
                continue
            matched.append(role)
    return [f"{role}审批" for role in matched]


def _normalized_amounts(text: str) -> list[str]:
    amounts = _AMOUNT_RE.findall(text or "")
    normalized = []
    for amount in amounts:
        compact = re.sub(r"\s+", "", amount).replace(",", "")
        normalized.append(compact)
    return _dedupe(normalized)


def _amount_aliases(text: str) -> list[str]:
    aliases: list[str] = []
    for amount in _normalized_amounts(text):
        match = re.fullmatch(r"(\d+)元", amount)
        if not match:
            continue
        value = int(match.group(1))
        if value >= 10000 and value % 10000 == 0:
            aliases.append(f"{value // 10000}万元")
    return _dedupe(aliases)


def _has_security_incident_evidence(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "安全事件",
            "信息安全事件",
            "数据泄露",
            "系统被入侵",
            "设备丢失",
            "电脑丢失",
            "笔记本丢失",
            "终端丢失",
            "资产丢失",
        )
    )


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _clean_keyword(value: object) -> str:
    text = _clean_text(str(value or ""))
    return text.strip("：:，,。；;、| ")


def _dedupe(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_keyword(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
