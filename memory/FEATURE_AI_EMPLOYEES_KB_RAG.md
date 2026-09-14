# Feature — AI Employees chat · ai_knowledge_base RAG wire-in

**Phase**: Feb-2026  
**Scope**: Backend (retrieval + injection) + Frontend (sources UI).  
**Audit result**: **Path B — text search** (no embeddings anywhere in
the codebase; ingestion pipeline for embeddings is a separate,
larger phase).

## Summary

The AI Employees chat endpoint
(`POST /api/ai-employees/{eid}/conversations/{cid}/messages`) now runs
a lightweight keyword-based retrieval against the tenant's
`ai_knowledge_base` collection before every LLM turn. Top-5 relevant
docs are:

1. Prepended to the system prompt as a Markdown context block.
2. Attached to the response envelope + persisted onto the assistant
   message row (so history replays keep the citation trail).
3. Surfaced in the AI Dock UI as a collapsible **"Sources referenced"**
   panel below the assistant message.

Action-draft turns (`body.action` set) **skip** retrieval — their own
structured context already covers the tool-shaped path.

## Retrieval algorithm (Path B — text search)

Each incoming user query is tokenised (lowercase, dedup, stripped of a
small English stop-word list, tokens `>= 2` chars). Every active,
non-deleted KB row for the tenant is then scored:

| Signal | Weight |
|--------|-------:|
| Token present in `title` | **3.0** |
| Token present in `tags[]` | 2.0 |
| Token present in `content_md` | 1.0 |

Ties break by `kind` order (`company_profile` > `policy` > `faq` >
`custom`), then `updated_at` DESC (most-recent wins). Top **K=5** wins.

Snippet: first 200-char window containing the strongest matched
token; falls back to the head of `content_md` when no token appears in
the body.

## Prompt injection template

```markdown
# Reference material from your company's knowledge base
(Cite the doc titles verbatim when quoting.)

## [Doc 1] {title}
_Kind: {kind}_
{snippet}
---
## [Doc 2] {title}
...

Answer the user's question using this material when applicable.
If the material does not answer the question, say so plainly.
```

The block is prepended to the existing employee + brand-brain system
prompt so downstream tool loops (Soshie, Vizzy, etc.) still see the
same context they always did.

## Response payload delta

`POST /api/ai-employees/{eid}/conversations/{cid}/messages` now
returns:

```json
{
  "user_message":     { ...unchanged... },
  "assistant_message":{
    ...unchanged fields...,
    "sources": [
      {"doc_id": "...", "title": "...", "snippet": "...",
       "kind": "policy", "score": 4.0},
      ...
    ]
  },
  "action":  { ...unchanged... },
  "sources": [ ...same list, envelope-level convenience... ]
}
```

- **Empty on no-match**: `sources: []` (always an array, never
  omitted — simpler client contract).
- **Persisted**: the same `sources` array is stored on the
  `ai_employee_messages` row so `GET .../messages` history replays
  keep citations visible.

## Frontend UX

- `frontend/src/components/AIDock/AIDock.jsx` — new inline
  `<SourcesBlock>` component below assistant bubbles.
- **Collapsed by default** — long chats stay scannable.
- Header: `📖 Sources referenced (N)` with chevron toggle.
- Each source row: title + `kind` chip + click-to-expand snippet.
- Testids:
  - `ai-response-sources` — the block itself
  - `ai-response-sources-toggle-<messageId>` — collapse/expand
  - `ai-source-<i>` — individual source row
  - `ai-source-<i>-toggle` — snippet expander
  - `ai-source-<i>-snippet` — visible snippet body
- Hidden entirely when `sources` is empty or the message is a `user`
  turn.

## Tenant scoping enforcement

- `retrieve_kb_sources(tenant_id, ...)` **always** filters
  `ai_knowledge_base.tenant_id`.
- Cross-tenant leak is tested explicitly
  (`TestRetrievalHelper.test_tenant_isolation` seeds a doc under a
  different tenant id and asserts the aquaterra retrieval never
  returns it).
- Soft-deleted (`is_deleted=True`) and inactive (`is_active=False`)
  rows are excluded from candidate pool.

## Telemetry event

Every retrieval emits a structured log at INFO:

```
[kb-rag] tenant=<id> tokens=<n> matches=<m> returned=<r>
         retrieval_ms=<ms> path=text
```

- `tokens` — number of usable tokens after stopword strip.
- `matches` — how many KB docs scored > 0.
- `returned` — top-K after cap.
- `retrieval_ms` — wall-clock retrieval time (Mongo round-trip +
  scoring in-process).
- `path` — always `text` in this phase; will flip to `embeddings`
  once ingestion ships.

Empty-KB and empty-token paths log at DEBUG so successful chats on
tenants without a KB stay quiet.

## Empty-KB / no-match handling

- Tenant with zero active KB docs → retrieval returns `[]`,
  response `sources = []`, chat behaviour identical to before this
  phase.
- Tenant with docs but no matching tokens → same.
- Query is empty / all stop-words → same.

## Future upgrade — embeddings (Path A)

When we later ship an ingestion pipeline that stores vector
embeddings on `ai_knowledge_base` documents, `retrieve_kb_sources`
gains a new path:

1. Embed the query via `emergent_integrations` (or provider) call.
2. Cosine-similarity across the tenant's stored vectors.
3. Fall back to text search when embeddings are missing on a doc
   (mixed-mode readiness).

The chat router does not change — same helper contract, same
`sources` payload. The `path` field in the telemetry line flips to
`embeddings` so ops can chart the migration.

## API surface delta

- **No new routes** — in-place enhancement of the existing chat
  endpoint. OpenAPI paths **unchanged** at 1744.
- **Modified response shape**: `sources[]` added on both
  `assistant_message` and envelope root.

## Test coverage

Backend (`backend/tests/test_ai_employees_kb_rag.py`) — **16 tests
passing**:

- Tokenizer: lowercases + dedupes, strips stopwords, handles empty
- Scoring: title > body, tag contribution, empty tokens
- Retrieval helper: active-only, tenant isolation, empty query,
  no-match, `top_k` cap, result shape
- Prompt formatter: empty input, includes title + snippet
- Endpoint: sources returned for matching KB queries, empty sources
  for unrelated queries

Frontend (`frontend/src/test/ai-dock-kb-sources.test.jsx`) —
**4 tests passing**:

- Renders collapsible block when sources present
- Snippet expander toggles per-source content
- No block on `user`-role messages
- No block when `sources` is `[]` or absent
- AI Dock default export still loads after wire-in

## Out of scope

- Any new document ingestion / embedding backfill pipeline.
- Full-text `$text` index on `ai_knowledge_base` (regex-based scoring
  is sufficient at current KB sizes; add index later when tenants
  exceed ~500 docs).
- Copilot (`ai_brain.py`) retrieval — separate surface, already reads
  the full KB verbatim.
- A–F backlog items.
