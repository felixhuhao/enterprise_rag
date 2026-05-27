# Document Detail & Chunk Viewer — Design Spec

## Scope

Add a document detail page that shows document metadata and a searchable chunk list. This is Step 1 from FUTURE_PLAN.md. Citation jump-from navigation is deferred to a later iteration.

## Architecture Decision: Single-page vertical layout (Approach A)

Document metadata card at top, chunk table below. All information visible on one page without switching views.

Why not alternatives:
- Left-right split: metadata fields (6-8) don't justify a permanent sidebar
- Tab layout: metadata and chunks are tightly coupled context, separating them adds friction

---

## 1. Backend API

### New endpoint

```
GET /api/documents/{document_id}/chunks
```

Returns document metadata (from SQLite) + chunks in one response.

Chunk source priority:

1. Milvus chunks are the primary source because they represent the retrievable knowledge base.
2. If Milvus returns no chunks and `parsed_dir/chunks.json` exists, fall back to parsed artifact chunks.
3. If neither source exists, return an empty chunks array.

The fallback is important for failed ingestion debugging. A document can finish chunking and then fail during embedding or Milvus saving; in that case `chunks.json` exists but Milvus has no retrievable chunks.

**Implementation:**

- Query Milvus using `client.query()` with filter `document_id == "{document_id}"`
- Output fields: all metadata columns, exclude `dense` and `sparse` vectors
- If collection does not exist, return `[]` rather than raising
- Sort by `page ASC, chunk_key ASC, milvus_chunk_id ASC`
- If Milvus returns no rows, load `data/general_parsed/{document_id}/chunks.json` if it exists
- Add computed field `content_length = len(content)` to each chunk
- Parse `image_paths` from JSON string to list
- Document metadata comes from existing `document_service.get_document()`
- Response includes `chunks_source`: `"milvus" | "parsed_artifact" | "none"`

**Chunk identity:**

- `milvus_chunk_id`: Milvus auto id. Useful for inspecting the current vector store row, but not stable across re-ingestion.
- `chunk_key`: stable application-level chunk id. Required for future citation-to-chunk navigation and graph-ready metadata.

For the first implementation, derive `chunk_key` deterministically when possible:

```
{document_id}:{source_type}:{table_id}:{part}:{sequence_index}
```

If a chunk already has a stored `chunk_key`, preserve it. Future ingestion should write `chunk_key` into both `chunks.json` and Milvus.

**Response shape:**

```json
{
  "chunks_source": "milvus",
  "document": {
    "document_id": "abc123",
    "filename": "report.pdf",
    "file_type": "pdf",
    "entity_name": "XX Corp",
    "status": "completed",
    "chunk_count": 42,
    "image_count": 8,
    "created_at": "2026-05-20T10:00:00",
    "updated_at": "2026-05-20T10:05:32"
  },
  "chunks": [
    {
      "chunk_key": "abc123:text::0:0001",
      "milvus_chunk_id": 12345,
      "document_id": "abc123",
      "file_title": "report.pdf",
      "entity_name": "XX Corp",
      "content": "chunk text...",
      "title": "1.1 Section",
      "parent_title": "Chapter 1",
      "section_title": "Chapter 1 > 1.1 Section",
      "part": 0,
      "page": 3,
      "source_type": "text",
      "table_id": null,
      "table_title": null,
      "raw_table_path": null,
      "table_tokens": null,
      "image_paths": [],
      "content_length": 256
    }
  ]
}
```

**Error handling:**

- 404 if document not found in SQLite
- Empty chunks array if document exists but has no chunks in Milvus or parsed artifacts
- `chunks_source = "parsed_artifact"` means chunks were produced by chunking but are not necessarily embedded/searchable
- `chunks_source = "none"` means no chunk artifact is available yet
- No search parameter on backend — search is frontend-only (chunk count per document is typically 10-200)

**Files to modify:**

- `backend/app/api/documents.py` — add route handler
- `backend/app/rag/vectorstores/general_milvus.py` — add `query_chunks_by_document_id()` function
- `backend/app/services/document_service.py` or a small helper — load `parsed_dir/chunks.json` fallback

---

## 2. Frontend Route & Navigation

### New route

```
/documents/:document_id → DocumentDetailView.vue
```

### Navigation entry

In `DocumentsView.vue` document table, the filename column becomes a clickable link:

- Blue link styling on filename text
- Click: `router.push('/documents/' + record.document_id)`
- Existing status tags and action buttons unchanged

### Back navigation

Detail page header: back arrow + "返回文档列表" link, using `router.push('/documents')`.

Do not rely only on `router.back()`: users may refresh or directly open a document detail URL.

### New files

- `frontend/src/components/documents/DocumentDetailView.vue`
- `frontend/src/api/documents.ts` — add `getDocumentChunks(documentId: string)` function

No new Pinia store needed — page data managed with component `ref`.

---

## 3. Document Metadata Section

Top card with document info, styled consistently with existing `documents-card` pattern.

**Layout:**

```
[← 返回文档列表]

文件名.pdf                    [已完成]
文档主体：XX公司年报

--- separator ---

文件类型    文档主体    Chunks    图片    上传时间           完成时间
PDF         XX公司      42        8      2026-05-20 10:00   2026-05-20 15:32
```

**Fields:**

- Title: filename with file type icon (reuse PDF red / MD accent color)
- Status tag: reuse `statusLabel` / `statusColor` from DocumentsView
- Entity name display, "—" if empty
- Stats row: grid layout matching existing `summary-row` style
- Timestamps formatted same as list page (`formatTime`)
- Failed documents: show error message row with error code + hint (reuse `ERROR_HINTS`)
- Chunk source badge:
  - `milvus`: "已入库"
  - `parsed_artifact`: "仅解析产物，尚未入库"
  - `none`: "暂无切片"

Failed documents can still be viewed. They may have retrievable chunks in Milvus, parsed-only chunks in `chunks.json`, or no chunks depending on the failed stage.

---

## 4. Chunk List Section

Below the metadata card.

### Search bar

Top row: search input + chunk count display (e.g. "共 42 个 chunks").

Search is frontend `computed` filter: `content.includes(keyword)`, real-time as user types.

### Chunk table

Using `a-table` with columns:

| Column | Field | Width | Notes |
|--------|-------|-------|-------|
| # | row index | 50px | 1-based sequence number |
| 章节 | section_title | 180px | Full title path, "—" if empty |
| 页码 | page | 60px | Centered, "—" if null |
| 类型 | source_type | 80px | Tag: text=blue, table_*=orange |
| 长度 | content_length | 70px | Centered, character count |
| 内容预览 | content | auto | Truncated 200 chars, expandable |
| 图片 | image_paths | 60px | Centered, count badge if > 0 |

### Content preview interaction

- Default: single-line truncated, first 200 characters
- Click row to expand full content (`a-table` expandable row)
- Expand area has copy button in top-right corner: `navigator.clipboard.writeText(content)`

### Table features

- Pagination: 20 per page
- Sortable: by page, content_length
- source_type tag color coding: `text` = arcoblue, `table_summary`/`table_full`/`table_row_group` = orange

---

## Out of Scope (Future Iterations)

- Citation jump-to-chunk navigation from chat page
- Highlight chunks that were retrieved for a query
- Parsed Markdown preview
- Image/table chunk distinct rendering
