# Phase 13 Manual Test Assets

These files are intentionally small and synthetic. They are meant for manual
testing of document parsing and chunk quality governance.

Upload from the app document page:

1. `phase13_normal.md`: expected `good`.
2. `phase13_missing_titles.md`: expected `missing_section_title`.
3. `phase13_low_information.md`: expected `low_information_chunk` and
   `undersized_chunk`.
4. `phase13_duplicate.md`: expected `duplicate_chunk`.
5. `phase13_oversized_table.md`: expected `oversized_chunk` on the table chunk.
6. `phase13_md_zip_with_image.zip`: expected successful Markdown zip parsing and
   image asset copy.
7. `phase13_pdf_policy.pdf`: expected successful PDF upload and parsing when
   MinerU is available.

Expected checks:

- New documents produce `chunks.json`, `chunk_quality.json`, and
  `processing_history.json`.
- Document detail shows the chunk quality panel.
- Warning chunks are marked in the chunk table.
- The "only warnings" filter works.
- Old documents without `chunk_quality.json` still open without breaking.

Notes:

- The ZIP includes one small PNG image referenced by `document.md`.
- If image description credentials are not configured, the image description
  step may mark the image as failed; that is still useful for image warning
  behavior.
- The oversized table file uses a long table cell to encourage an oversized
  table chunk. If chunking settings change, the warning may shift from
  `oversized_chunk` to normal table chunks.
