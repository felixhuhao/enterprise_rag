# Keyword Matching Pattern Audit

**Date:** 2026-06-11
**Scope:** Full codebase scan for hardcoded keyword matching patterns
**Total Findings:** 14 across 10 source files

The core RAG pipeline (embedding, vector search, LLM generation, reranking) uses genuine AI/ML. However, nearly all routing, classification, and enrichment decisions rely on hardcoded Chinese keyword matching. This report catalogs every instance.

---

## CRITICAL

### Finding 1: Chunk Enrichment Tag Classification

**File:** `backend/app/rag/chunking/enrichment.py`
**Lines:** 33-277

Entire chunk enrichment (which feeds BM25/sparse search) uses hardcoded keyword lists and if-elif chains.

**Hardcoded word lists (lines 33-34):**
```python
_THRESHOLD_WORDS = ("超过", "以下", "以上", "以内", "低于", "高于", "不低于", "不超过", "大于", "小于")
_APPROVAL_WORDS = ("审批", "批准", "签字", "审核", "复核")
```

**Hardcoded role list (lines 35-51):**
```python
_ROLES = (
    "CEO", "CFO", "CTO", "VP", "分管VP",
    "总经理", "技术总监", "采购部总监", "部门总监",
    "直属经理", "部门经理", "审批人", "负责人", "主管", "经理",
)
```

**Keyword-to-tag mapping via if-elif chains (lines 82-105):**
```python
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
```

**Keyword-to-recall-terms expansion (lines 168-222):**
```python
if "payment_rule" in tag_set:
    terms.extend(["付款金额", "支付金额"])
    if has_approval:
        terms.extend(["付款审批", "支付审批"])
if "budget_rule" in tag_set:
    terms.extend(["预算金额"])
    ...
if "security_incident_rule" in tag_set:
    terms.extend([
        "安全事件", "信息安全事件", "数据泄露", "系统被入侵",
        "设备丢失", "电脑丢失", "笔记本丢失", "终端丢失", "资产丢失",
    ])
```

**Security incident detection (lines 263-277):**
```python
def _has_security_incident_evidence(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "安全事件", "信息安全事件", "数据泄露", "系统被入侵",
            "设备丢失", "电脑丢失", "笔记本丢失", "终端丢失", "资产丢失",
        )
    )
```

**Reliability Concern:** This is the core chunk enrichment system. Tag classification and recall term generation are entirely rule-based using hardcoded Chinese keywords. Any document using synonyms, alternative phrasing, or domain-specific jargon not in these lists will be misclassified or entirely missed. The role list is static; new roles from policy updates will never be detected. Does not scale to different enterprise domains or languages.

---

## HIGH

### Finding 2: Multi-Hop Discovery Trigger

**File:** `backend/app/rag/query/multi_hop.py`
**Lines:** 20-36, 75-76

**Hardcoded keyword lists (lines 20-29):**
```python
DISCOVERY_KEYWORDS = [
    "哪些公司", "哪些企业", "什么公司",
    "竞争对手", "竞争企业", "竞品",
    "供应商", "客户", "合作伙伴",
    "各自", "分别",
]

RESPONSIBILITY_HOP_KEYWORDS = [
    "谁负责", "由谁负责", "负责人", "这个人", "此人", "还负责", "负责什么",
]
```

**Keyword-based routing decision (lines 32-36):**
```python
def _decide_multi_hop(entity_mode: str, query: str) -> bool:
    if entity_mode not in ("broad", "none"):
        return False
    return any(kw in query for kw in DISCOVERY_KEYWORDS + RESPONSIBILITY_HOP_KEYWORDS)
```

**Reliability Concern:** Whether the system enters multi-hop retrieval depends entirely on checking for specific Chinese phrases. Queries like "列出所有涉及的公司", "关联实体", "相关方" or any English phrasing bypass multi-hop entirely and get inferior results.

### Finding 3: Error Classification

**File:** `backend/app/errors.py`
**Lines:** 35-55

```python
def classify_error(exc: Exception) -> AppErrorCode:
    msg = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    if "mineru" in msg or "mineru" in exc_type:
        return AppErrorCode.MINERU_API_ERROR
    if any(k in msg for k in ("embedding", "embed", "embeddings")) or "embedding" in exc_type:
        return AppErrorCode.EMBEDDING_ERROR
    if "milvus" in msg or "pymilvus" in exc_type:
        return AppErrorCode.MILVUS_ERROR
    if any(k in msg for k in ("dashscope", "openai", "llm", "chat", "timeout")):
        return AppErrorCode.LLM_ERROR

    return AppErrorCode.UNKNOWN_ERROR
```

**Reliability Concern:** `"chat" in msg` means any chat-related database error is misclassified as `LLM_ERROR`. `"timeout" in msg` misclassifies any timeout (e.g., database timeout) as an LLM error. Fragile substring matching can mask real issues.

---

## MEDIUM-HIGH

### Finding 4: Entity Broad-Signal Detection

**File:** `backend/app/rag/query/entity_confirm.py`
**Lines:** 11-16, 100-101

```python
_BROAD_SIGNALS = [
    "所有公司", "所有企业", "全部公司", "全部企业",
    "哪些公司", "哪些企业", "各公司", "各企业",
    "整体", "全部", "各家", "每家公司", "每家企业",
    "所有实体", "全部实体", "各个公司",
]

def _has_broad_signal(query: str) -> bool:
    return any(sig in query for sig in _BROAD_SIGNALS)
```

**Reliability Concern:** Determines whether the system enters "broad" entity mode. "企业间数据汇总", "跨公司统计" would not trigger broad mode. Chinese-language-only signals exclude internationalized queries.

### Finding 5: Synthesis Query Detection (Duplicated)

**File:** `backend/app/rag/query/planner.py` lines 21-23, 235-236
**File:** `backend/app/rag/query/build_prompt.py` lines 88-90, 150-151

Same keyword list defined in **two separate files** — risk of divergence:

```python
SYNTHESIS_QUERY_MARKERS = (
    "比较", "关联", "区别", "异同", "一致", "不同", "分别", "各自", "对比",
)

def _needs_synthesis_budget(query: str) -> bool:
    return any(marker in query for marker in SYNTHESIS_QUERY_MARKERS)
```

**Reliability Concern:** Budget allocation and prompt template selection depend on detecting these exact words. Implicit comparisons (e.g., "A公司 和 B公司 的费用政策") are missed. Two copies of the same list risk divergence over time.

---

## MEDIUM

### Finding 6: Deterministic Query Expansion

**File:** `backend/app/rag/query/query_expansion.py`
**Lines:** 87-95

```python
def _deterministic_expansions(query: str) -> list[str]:
    text = query or ""
    has_amount = any(word in text for word in ("金额", "费用", "预算", "阈值", "门槛", "额度", "上限", "下限"))
    has_approval = any(word in text for word in ("审批", "批准", "权限", "签字", "审核"))
    if has_amount and has_approval:
        return [
            "金额审批阈值 费用审批门槛 预算审批 报销审批 采购审批 付款审批 外部培训费用审批 供应商付款 项目预算"
        ]
    return []
```

**Reliability Concern:** Only triggers for the specific combination of amount + approval keywords. The expansion itself is a single hardcoded string, not dynamically generated. A thin rule-based layer pretending to add query understanding.

### Finding 7: Pronoun Resolution

**File:** `backend/app/rag/query/rewrite_query.py`
**Lines:** 11-15, 33-37

```python
_PRONOUNS = [
    "这家公司", "该公司", "这家企业", "该企业",
    "它的", "它的", "该公司的", "该企业的",
    "它", "其",
]

rewritten = query
for pronoun in _PRONOUNS:
    if pronoun in rewritten:
        rewritten = rewritten.replace(pronoun, entity, 1)
```

**Reliability Concern:** "其" is a very common Chinese character appearing in many non-pronoun contexts ("其次", "其中", "极其"). Replacing it with an entity name corrupts the query. "它" similarly appears in many contexts. No NLP/POS tagging to distinguish pronoun usage.

### Finding 8: Refusal Signal Detection (Eval)

**File:** `backend/scripts/eval_golden/numeric.py`
**Lines:** 5-15, 45-46

```python
REFUSAL_SIGNALS = [
    "知识库中", "文档中没", "没有找到", "无法提供", "暂无",
    "未包含", "不包含", "未披露", "未发布", "尚无",
    "没有足够", "不在知识库", "无法回答", "未能找到",
    "未提及", "未涉及", "不涉及", "没有提及", "没有涉及",
    "没有相关信息", "无法确认", "没有覆盖", "未覆盖",
    "没有该", "不包含该", "没有关于",
    "没有披露", "尚未发布", "未知", "无法确定",
    "无任何来源", "没有数据", "无法判断",
]

def _has_refusal_signal(answer: str) -> bool:
    return any(sig in answer for sig in REFUSAL_SIGNALS)
```

**Reliability Concern:** "未知" in "这个未知领域..." triggers false positive refusal detection. Novel refusal phrasings not in this list are missed. Classic toy sentiment analysis approach.

### Finding 9: Hardcoded Entity Names in Scoring (Eval)

**File:** `backend/scripts/eval_golden/scorers.py`
**Lines:** 208-233

```python
if na_type == "out_of_scope_entity":
    entity_names = ["华虹半导体", "台积电", "三星", "英特尔", "英伟达"]
    asked_entity = next((en for en in entity_names if en in question), "")
```

**Reliability Concern:** Out-of-scope entity check only knows 5 hardcoded company names. Any new test case with a different out-of-scope entity silently skips the hallucination check, giving false passes.

### Finding 10: Keyword-Based Answer Scoring (Eval)

**File:** `backend/scripts/eval_golden/numeric.py` lines 203-210
**File:** `backend/scripts/eval_golden/scorers.py` lines 62-64, 87-91

```python
def _keyword_in_answer(keyword: str, answer: str) -> bool:
    if not keyword:
        return False
    compact_answer = _compact_keyword_text(answer)
    return any(
        variant in answer or _compact_keyword_text(variant) in compact_answer
        for variant in _keyword_variants(keyword)
    )
```

```python
expected_kw = item.get("expected_keywords", [])
kw_hits = [kw for kw in expected_kw if _keyword_in_answer(kw, answer)]
kw_score = len(kw_hits) / len(expected_kw) if expected_kw else 1.0
```

**Reliability Concern:** Answer quality scoring uses keyword presence checking. Correct answers phrased differently score poorly. Wrong answers mentioning expected keywords score well. This drives 70% of the final eval score in legacy mode.

---

## LOW

### Finding 11: RRF Fusion Mode Label Routing

**File:** `backend/app/rag/query/rrf_fusion.py`
**Lines:** 69-73, 95-106

```python
def _mode_label(mode: str) -> str:
    if not mode:
        return "primary"
    if mode == "disabled":
        return "disabled"
    if mode.startswith("hyde"):
        return "hyde_fallback" if "fallback" in mode else "hyde"
    if mode.startswith("dense"):
        return "dense"
    if mode.startswith("hybrid"):
        return "hybrid_fallback" if "fallback" in mode else "hybrid"
    return mode
```

**Reliability Concern:** Mode string parsing uses substring matching. Currently safe but fragile if mode naming changes.

### Finding 12: Fallback Detection (Duplicated x3)

**Files:**
- `backend/app/rag/query/search_pipeline.py:200-202`
- `backend/app/api/query_chat.py:480-482`
- `backend/app/services/retrieval_test_formatting.py:62-64`

Identical pattern in all three:
```python
"fallback" in state.get("search_mode", "")
    or "fallback" in state.get("search_mode_hyde", "")
    or any("fallback" in mode for mode in state.get("search_modes_expanded", []))
```

**Reliability Concern:** Same fragile string-matching pattern duplicated in 3 places. Should use structured state rather than string parsing.

### Finding 13: Entity Name Extraction from Filename

**File:** `backend/app/rag/ingestion/service.py`
**Lines:** 7-35

```python
def extract_entity_name(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    parts = re.split(r"[_\-\s【】《》（）()]", stem)
    parts = [p.strip() for p in parts if p.strip()]
    date_pattern = re.compile(
        r"^(\d{4}|\d{2,4}[年/-]\d{1,2}[月/-]?\d{0,2}[日号]?|"
        r"\d{4}[QqHh][1-4]|年报|半年报|季报|一季报|三季报)$"
    )
    candidates = [p for p in parts if not date_pattern.match(p) and not re.match(r"^\d+$", p)]
    if not candidates:
        return ""
    return candidates[0]
```

**Reliability Concern:** Purely rule-based with hardcoded Chinese date/report-type patterns. Non-standard filenames or other languages may produce incorrect entity names. Takes the first non-date, non-numeric part, which may not be the entity name.

### Finding 14: Frontend Label Mappings

**Files:** `frontend/src/utils/labelMaps.ts` lines 1-161, `frontend/src/utils/errorHints.ts` lines 1-12

```typescript
export const ERROR_HINTS: Record<string, string> = {
  MINERU_API_ERROR: '文档解析服务异常，请稍后重试',
  EMBEDDING_ERROR: '向量化服务异常，请稍后重试',
  MILVUS_ERROR: '向量数据库异常，请检查 Milvus 连接',
  LLM_ERROR: '大模型服务异常，请稍后重试',
  NO_CONTEXT_FOUND: '未找到相关内容，请尝试换个表述或上传更多文档',
}
```

**Reliability Concern:** UI-only display mappings. Least concerning pattern. Only risk is new error codes/modes showing raw keys until frontend is updated.

---

## Summary

| # | File | Lines | Pattern Type | Severity | In Core Pipeline? |
|---|------|-------|-------------|----------|-------------------|
| 1 | `enrichment.py` | 33-277 | Hardcoded keyword lists, keyword-to-tag mapping, rule-based classification | CRITICAL | Yes (ingestion) |
| 2 | `multi_hop.py` | 20-36 | Hardcoded intent detection, keyword-based routing | HIGH | Yes (retrieval) |
| 3 | `errors.py` | 35-55 | Keyword-in-message error classification | HIGH | Yes (error handling) |
| 4 | `entity_confirm.py` | 11-16 | Hardcoded intent detection | MED-HIGH | Yes (retrieval) |
| 5 | `planner.py` + `build_prompt.py` | 21-23, 88-90 | Duplicate keyword lists, intent detection | MED-HIGH | Yes (retrieval) |
| 6 | `query_expansion.py` | 87-95 | Keyword-based expansion trigger | MEDIUM | Yes (retrieval) |
| 7 | `rewrite_query.py` | 11-37 | Hardcoded pronoun list + naive replacement | MEDIUM | Yes (retrieval) |
| 8 | `numeric.py` (eval) | 5-46 | Toy refusal detection via word list | MEDIUM | Eval only |
| 9 | `scorers.py` (eval) | 208-233 | Hardcoded entity names for scoring | MEDIUM | Eval only |
| 10 | `numeric.py` + `scorers.py` | 203-210, 62-64 | Keyword matching for answer scoring | MEDIUM | Eval only |
| 11 | `rrf_fusion.py` | 69-106 | Keyword-in-string mode detection | LOW | Yes (retrieval) |
| 12 | 3 files | Multiple | Duplicated fallback string matching | LOW | Yes |
| 13 | `service.py` (ingestion) | 7-35 | Rule-based entity name extraction | LOW | Yes (ingestion) |
| 14 | `labelMaps.ts` + `errorHints.ts` | 1-161, 1-12 | Static display label mappings | LOW | Frontend only |

## Severity Distribution

| Severity | Count | Pipeline Impact |
|----------|-------|-----------------|
| CRITICAL | 1 | Ingestion enrichment — directly limits retrieval quality |
| HIGH | 2 | Multi-hop routing, error classification |
| MED-HIGH | 2 | Entity mode, synthesis detection |
| MEDIUM | 4 | Query expansion, pronoun resolution, eval scoring |
| LOW | 4 | Mode labels, filename parsing, UI mappings |

## Overall Assessment

1. **Chunk enrichment** (Finding 1) is entirely rule-based — this data feeds into BM25/sparse search. Its quality directly limits retrieval quality.
2. **Multi-hop activation** (Finding 2) uses a closed keyword list — users who phrase discovery queries differently get flat search.
3. **Error classification** (Finding 3) can misattribute errors due to substring collisions.
4. **Synthesis detection** (Finding 5) is duplicated and keyword-only, missing implicit comparison queries.
5. **Pronoun resolution** (Finding 7) risks false positives from common Chinese characters like "其" and "它".

The eval system itself (Findings 8-10) also relies on keyword matching, meaning quality metrics may not accurately reflect real system quality — both false positives (wrong answers with keywords) and false negatives (correct answers without expected keywords) undermine confidence in test results.
