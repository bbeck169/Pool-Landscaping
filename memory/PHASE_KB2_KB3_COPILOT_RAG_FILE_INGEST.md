# Phase KB2 + KB3 · Feb-2026 — Copilot RAG refactor + KB file ingestion

## KB2 · Copilot uses the shared retriever

### What changed
`_build_system_prompt(tenant_id, query=None)` in `backend/routers/ai_brain.py`:
* When a query is passed → calls `services.ai_kb_retrieval.retrieve_kb_sources` +
  `format_kb_context` (the same helpers AI Employees uses) and returns
  only the top-5 snippets.
* When the retriever returns `[]` → returns a short "no relevant
  knowledge found" preamble.  Never dumps the full KB.
* When `query` is `None`/empty → legacy full-concat, hard-capped at
  16 000 chars (~4 000 tokens) with a `[copilot-kb] fallback
  full-concat used…` info log for observability.

`copilot_message` now passes `body.message` as the retrieval query.
`GET /api/ai/knowledge/system-prompt?q=…` accepts an optional query
so the Admin UI can preview the same shape.

### Token-count savings on a synthetic 20-row KB
```
20-row KB · UNCAPPED old code would have been : 31,730 chars  ~7,932 tokens
20-row KB · legacy full-concat (capped @16k)  : 14,541 chars  ~3,635 tokens
20-row KB · RAG top-5 (KB2 path)              :    827 chars  ~  206 tokens
```

### Live proof — 3 audit questions on the aquaterra Copilot
* **"What is our brand voice?"** →
  > Based on our company profile, our brand voice is: **Friendly, direct, no fluff.**
  > We keep communications clear and straightforward. We're approachable but get to the point without unnecessary language or marketing speak.
* **"How do we quote prices?"** →
  > Based on our company knowledge base, here's our policy on quoting prices: **We never quote prices without admin approval.** This is a firm rule stated in our company profile…
* **"What is our service area?"** →
  > Based on our company profile, **Pool & Landscaping of Vistancia services the greater Peoria & Vistancia, Arizona area.**

All three remain KB-accurate.  AI Employees flow (verified via
`test_ai_employees_kb_rag.py`) is unchanged.

## KB3 · KB file ingestion

### What ships
* **New endpoint**: `POST /api/ai/knowledge/file` (in OpenAPI as
  `operation_id="ai.knowledge.fileIngest"`).
* **Accepts**: `application/pdf`, DOCX, `text/plain`, `text/markdown`
  via multipart form.  `title`, `kind`, `tags` optional.
* **Rejects**: >25 MB → 413, wrong content-type → 415, empty-extraction
  (scanned PDF) → 400 `extraction_empty`, non-admin → 403.
* **Storage**: original binary goes through the same
  `services.file_storage.put_object` primitive the customer_equipment
  photos + `/api/files/upload` use.  Path is
  `poolscape-crm/{tenant_id}/ai-knowledge/{uuid}.{ext}`.
* **Extraction**: `pypdf` for PDF, `python-docx` for DOCX, UTF-8
  (latin-1 fallback) for TXT/MD.  Extracted text lands in
  `ai_knowledge_base.content_md` so the existing retriever picks
  it up automatically — no parallel index.
* **New KB row fields** (soft, no migration): `source_type` and
  `source_file_id`.  Legacy manual-paste rows are unaffected.

### Frontend
* New `KBFileUploadModal.jsx` under `frontend/src/pages/settings/`.
* `AIBrainPage.jsx` now has an "Upload file" button next to the
  existing "New entry" button; source-type badge appears on each KB
  list row for ingested docs; a "View original" link opens the S3
  file when `source_file_id` is set.
* Shared XHR-with-progress helper `uploadKnowledgeFile` in
  `frontend/src/api/files.js` (sibling of `uploadFile`).

### Live proof
Uploaded `pool_warranty.pdf` as `super@aquaterra.com`.  KB row
persisted with `source_type=pdf`, `source_file_id` linked, `content_md`
= "The pool warranty covers 5 years on the shell but 2 years on the
pump.  Contact us within 30 days of failure."

* **Copilot** — "How long is the pool warranty on the pump?":
  > According to our Pool Warranty Terms documentation, the pool
  > warranty covers **2 years on the pump** (while the shell is
  > covered for 5 years). If you experience any pump issues,
  > please contact us within 30 days of the failure to initiate
  > a warranty claim.
* **AI Employee (Casey)** — same question:
  > Based on our warranty terms, the pump is covered for **2 years**.
  > (The pool shell itself has a longer 5-year warranty.) …

## Tests
* Backend pytest (12 new · 39 across the KB neighborhood, 100% green):
  * `test_copilot_shared_retriever.py` — 4 cases.
  * `test_kb_file_ingestion.py` — 8 cases.
* Frontend vitest — `kb-file-upload-modal.test.jsx` (3 cases) +
  full suite 4483 passed | 34 skipped | 0 failed.

## Retrieval-side confirmation
`services.ai_kb_retrieval.retrieve_kb_sources` reads from
`ai_knowledge_base.content_md` — the exact same field the KB3 ingest
writes to.  No retriever code changes required.  Both surfaces
(Copilot + AI Employees) pick up ingested rows on the very next turn,
proven end-to-end by the "pump warranty" round-trip above.

## Files changed
* `backend/routers/ai_brain.py` — `_build_system_prompt` refactor +
  new `POST /ai/knowledge/file` endpoint.
* `backend/tests/test_copilot_shared_retriever.py` (new)
* `backend/tests/test_kb_file_ingestion.py` (new)
* `backend/requirements.txt` — `python-docx==1.2.0` added via
  `pip install && pip freeze`.
* `frontend/src/api/files.js` — added `uploadKnowledgeFile` helper.
* `frontend/src/pages/settings/AIBrainPage.jsx` — "Upload file"
  button, source-type badge, "View original" link.
* `frontend/src/pages/settings/KBFileUploadModal.jsx` (new).
* `frontend/src/test/kb-file-upload-modal.test.jsx` (new).

## Deviations
None.  Kept the retriever's public signature unchanged (still takes
positional `tenant_id, query`), which means AI Employees didn't need
to change.
