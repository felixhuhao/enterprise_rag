"""Numeric and keyword matching for golden-set scoring."""

import re

REFUSAL_SIGNALS = [
    "知识库中", "文档中没", "没有找到", "未找到", "无法提供", "暂无",
    "未包含", "不包含", "未披露", "未发布", "尚无",
    "没有足够", "不在知识库", "无法回答", "未能找到",
    "未提及", "未涉及", "不涉及", "没有提及", "没有涉及",
    "没有相关信息", "无法确认", "没有覆盖", "未覆盖",
    "没有该", "不包含该", "没有关于",
    # LLM 拒绝变体补充
    "没有披露", "尚未发布", "未知", "无法确定",
    "无任何来源", "没有数据", "无法判断",
]

FINANCIAL_UNIT_PATTERN = r"(\d+\.?\d*)\s*(亿元|亿美元|百万美元|万片|%|港币|人民币)"
CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
UNIT_ALIASES = {
    "个季度": ["个季度", "季度"],
    "年": ["年"],
    "个月": ["个月", "月"],
    "天": ["天", "日"],
    "个工作日": ["个工作日", "工作日"],
    "小时": ["小时"],
    "分钟": ["分钟", "分"],
    "万元": ["万元", "万"],
    "元": ["元"],
}
NUMBER_PATTERN = r"-?\d[\d,]*(?:\.\d+)?"


def _has_refusal_signal(answer: str) -> bool:
    return any(sig in answer for sig in REFUSAL_SIGNALS)


# ---------------------------------------------------------------------------
# Numeric scoring
# ---------------------------------------------------------------------------

def _parse_chinese_int(value: str) -> int | None:
    """Parse simple Chinese integers used in policy text, up to 99."""
    value = value.strip()
    if not value:
        return None
    if value in CHINESE_DIGITS:
        return CHINESE_DIGITS[value]
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = CHINESE_DIGITS.get(left, 1 if left == "" else None)
        ones = CHINESE_DIGITS.get(right, 0 if right == "" else None)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return None


def _unit_aliases(unit: str) -> list[str]:
    return UNIT_ALIASES.get(unit, [unit] if unit else [])


def _parse_numeric_token(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _numeric_close(found: float, expected: float, tolerance: float) -> bool:
    if expected == 0:
        return found == 0
    return abs(found - expected) / abs(expected) <= tolerance


def _find_number_before_unit(answer: str, unit: str) -> list[float]:
    values: list[float] = []
    for unit_m in re.finditer(re.escape(unit), answer):
        start = max(0, unit_m.start() - 25)
        context = answer[start:unit_m.start()]
        for token in re.findall(NUMBER_PATTERN, context):
            value = _parse_numeric_token(token)
            if value is not None:
                values.append(value)
    return values


def _find_scaled_amount_match(answer: str, expected_val: float, expected_unit: str,
                              tolerance: float) -> bool:
    """Match Yuan/Wan-Yuan variants such as 3万元 == 30,000元."""
    if expected_unit in {"万元", "万"}:
        for unit in ("万元", "万"):
            for found in _find_number_before_unit(answer, unit):
                if _numeric_close(found, expected_val, tolerance):
                    return True
        expected_yuan = expected_val * 10000
        for found in _find_number_before_unit(answer, "元"):
            if _numeric_close(found, expected_yuan, tolerance):
                return True
        return False

    if expected_unit == "元":
        for found in _find_number_before_unit(answer, "元"):
            if _numeric_close(found, expected_val, tolerance):
                return True
        for unit in ("万元", "万"):
            for found in _find_number_before_unit(answer, unit):
                if _numeric_close(found * 10000, expected_val, tolerance):
                    return True
        return False

    return False


def _find_chinese_numeric_match(answer: str, expected_val: float, expected_unit: str,
                                tolerance: float) -> bool:
    if expected_val != int(expected_val):
        return False

    units = _unit_aliases(expected_unit)
    if expected_unit and not units:
        return False

    if expected_unit:
        for unit in units:
            pattern = rf"([零一二两三四五六七八九十]{{1,3}})\s*{re.escape(unit)}"
            for match in re.finditer(pattern, answer):
                found = _parse_chinese_int(match.group(1))
                if found is not None and abs(found - expected_val) <= max(tolerance * abs(expected_val), 0):
                    return True
        return False

    for token in re.findall(r"[零一二两三四五六七八九十]{1,3}", answer):
        found = _parse_chinese_int(token)
        if found is not None and abs(found - expected_val) <= max(tolerance * abs(expected_val), 0):
            return True
    return False


def _find_numeric_match(answer: str, expected_val: float, expected_unit: str,
                        tolerance: float) -> bool:
    """Check if expected_val with unit context appears in answer within tolerance."""
    if expected_unit:
        if expected_unit in {"万元", "万", "元"} and _find_scaled_amount_match(
            answer,
            expected_val,
            expected_unit,
            tolerance,
        ):
            return True

        # Find expected value near occurrences of the unit string or aliases.
        for unit in _unit_aliases(expected_unit):
            for found in _find_number_before_unit(answer, unit):
                if _numeric_close(found, expected_val, tolerance):
                    return True
        if _find_chinese_numeric_match(answer, expected_val, expected_unit, tolerance):
            return True
        return False
    else:
        # No unit constraint — find value anywhere
        for ns in re.findall(NUMBER_PATTERN, answer):
            found = _parse_numeric_token(ns)
            if found is None:
                continue
            if _numeric_close(found, expected_val, tolerance):
                return True
        return _find_chinese_numeric_match(answer, expected_val, expected_unit, tolerance)


def _keyword_variants(keyword: str) -> set[str]:
    variants = {keyword}
    match = re.fullmatch(r"(\d+)(.+)", keyword)
    if not match:
        return variants
    value = int(match.group(1))
    suffix = match.group(2)
    if value == 2:
        variants.add(f"两{suffix}")
    for chinese, parsed in CHINESE_DIGITS.items():
        if parsed == value:
            variants.add(f"{chinese}{suffix}")
    return variants


def _compact_keyword_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _keyword_in_answer(keyword: str, answer: str) -> bool:
    if not keyword:
        return False
    compact_answer = _compact_keyword_text(answer)
    return any(
        variant in answer or _compact_keyword_text(variant) in compact_answer
        for variant in _keyword_variants(keyword)
    )


def score_numeric(answer: str, numeric_expectations: list[dict]) -> dict:
    """Score numeric expectations with relative tolerance."""
    if not numeric_expectations:
        return {"numeric_score": None, "hits": [], "misses": []}

    hits, misses = [], []
    for exp in numeric_expectations:
        val = exp["value"]
        unit = exp.get("unit", "")
        tol = exp.get("tolerance", 0.01)
        label = f"{val}{unit}"
        if _find_numeric_match(answer, val, unit, tol):
            hits.append(label)
        else:
            misses.append(label)

    score = len(hits) / len(numeric_expectations)
    return {"numeric_score": round(score, 4), "hits": hits, "misses": misses}
