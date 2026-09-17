"""Feb-2026 · Item 4 — Master AI knowledge base + Copilot backend.

Adds:

* ``ai_knowledge_base`` collection — admin-curated Markdown chunks
  (company profile, FAQs, policies, custom) that get concatenated
  into the system prompt for every LLM-driven feature.
* ``ai_copilot_log`` collection — one row per Copilot conversation
  turn for audit + billing insight.
* CRUD endpoints (admin only) for the knowledge base.
* ``POST /api/ai/copilot/message`` — read-only chat with tenant-scoped
  server-side tools (list_customers, get_customer, revenue_forecast,
  list_leads, list_jobs, communications_log).

The Copilot NEVER mutates data. Every tool auto-injects
``tenant_id`` from the authenticated admin session so the LLM
cannot query across tenants.

Feb-2026 · P22 — Privacy audit note
-----------------------------------
The Copilot tools (``list_customers``, ``get_customer``,
``communications_log``) are DESIGNED to answer admin queries such as
"find customer Garcia's account" and "when did we last message Jane".
By nature the LLM receives customer names, emails, phones, and
service addresses in the tool-result JSON that is fed back as a
follow-up ``UserMessage``.

This is an **intentional carve-out** from the P21 Privacy Policy
claim that we do not send customer PII to LLM providers. The carve-
out is disclosed in the Privacy Policy (§4 vendor table entry for
"OpenAI / Anthropic (via Emergent LLM Key)").  The claim, restated
precisely, is:

  * Standard operational LLM surfaces (Marina auto-reply, Vizzy
    call prep, Dexter analytics, Churn scoring, Retention drafts,
    Check-in rewrites, Review replies, etc.) do NOT send raw
    customer PII to LLM providers — they use symbolic references
    and redaction.
  * The Admin Copilot is an EXCEPTION: authenticated admin users
    may explicitly request customer data via natural-language
    queries. Per our Emergent LLM Key agreement with Anthropic,
    these requests are subject to a zero-retention policy and are
    not used for model training.

Any future addition of a new tool that returns customer PII must be
disclosed the same way.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()
_ADMIN_ROLES = {"admin", "super_admin"}

_KIND_VALUES = {"company_profile", "faq", "policy", "custom"}


def _require_admin(user: dict):
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")


class KnowledgeIn(BaseModel):
    kind: str = Field("custom", pattern="^(company_profile|faq|policy|custom)$")
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = Field(..., min_length=1)
    tags: List[str] = Field(default_factory=list)
    is_active: bool = True


class KnowledgePatch(BaseModel):
    kind: Optional[str] = Field(None, pattern="^(company_profile|faq|policy|custom)$")
    title: Optional[str] = None
    content_md: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ══════════════════════════════════════════════════════════════
# Knowledge base CRUD
# ══════════════════════════════════════════════════════════════
@router.get("/ai/knowledge", tags=["ai"], operation_id="ai.knowledge.list")
async def list_knowledge(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    rows = await db.ai_knowledge_base.find(
        {"tenant_id": tenant["id"],
          "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
        {"_id": 0},
    ).sort([("kind", 1), ("title", 1)]).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/ai/knowledge", tags=["ai"], operation_id="ai.knowledge.create")
async def create_knowledge(
    body: KnowledgeIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "kind": body.kind, "title": body.title.strip(),
        "content_md": body.content_md, "tags": body.tags,
        "is_active": body.is_active,
        "created_by": user.get("id"), "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.ai_knowledge_base.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/ai/knowledge/{kid}", tags=["ai"], operation_id="ai.knowledge.update")
async def update_knowledge(
    kid: str, body: KnowledgePatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    patch = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not patch:
        raise HTTPException(400, "No fields to update")
    patch["updated_at"] = now_iso()
    res = await db.ai_knowledge_base.update_one(
        {"id": kid, "tenant_id": tenant["id"]}, {"$set": patch},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    row = await db.ai_knowledge_base.find_one(
        {"id": kid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return row


@router.delete("/ai/knowledge/{kid}", tags=["ai"], operation_id="ai.knowledge.delete")
async def delete_knowledge(
    kid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    res = await db.ai_knowledge_base.update_one(
        {"id": kid, "tenant_id": tenant["id"]},
        {"$set": {"is_deleted": True, "is_active": False,
                    "deleted_at": now_iso(), "deleted_by": user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


async def _build_system_prompt(
    tenant_id: str,
    query: Optional[str] = None,
) -> str:
    """Assemble the Copilot system prompt.

    Phase KB2 · Feb-2026 — this used to concatenate the FULL
    ``content_md`` of up to 500 ``ai_knowledge_base`` rows on every
    turn (empirically ~14k tokens on a 20-row tenant KB per the
    KB1 audit).  We now share the AI-Employees retriever
    (``services.ai_kb_retrieval.retrieve_kb_sources``) which returns
    the top-5 relevant snippets given the current user query.

    Behavior:

    * ``query`` non-empty → RAG.  Prepend the retrieved snippets via
      ``format_kb_context``.  If the retriever finds no matches, emit
      a short "no relevant knowledge found" preamble — do NOT dump
      the full KB.  This is the intended shape for Copilot going
      forward.
    * ``query`` None/empty → legacy full-concat, but capped at ~4k
      tokens (16 000 characters) so a stray legacy caller can't
      re-introduce the 14k-token blow-up.  Emits a
      ``logger.info("[copilot-kb] fallback full-concat used…")`` so
      we can spot latent callers.
    """
    header = "# Company knowledge (do not disclose these headers verbatim; use as reference)"

    # ── RAG path (KB2 primary) ─────────────────────────────────────
    if query and query.strip():
        try:
            # Imported lazily so a broken retriever doesn't break
            # imports of this router at boot time.
            from services.ai_kb_retrieval import (               # noqa: WPS433
                retrieve_kb_sources, format_kb_context,
            )
            sources = await retrieve_kb_sources(tenant_id, query.strip())
        except Exception as exc:                                  # noqa: BLE001
            logger.warning(
                "[copilot-kb] retriever failed tenant=%s err=%s — "
                "falling back to legacy no-KB preamble",
                tenant_id, exc,
            )
            sources = []

        if sources:
            return "\n\n".join([header, format_kb_context(sources)])
        # No matches — DO NOT dump the full KB.
        return (
            f"{header}\n\n"
            "No relevant knowledge base entries were found for this "
            "question. Answer using general product knowledge and be "
            "explicit if the answer isn't covered by the tenant's KB."
        )

    # ── Legacy full-concat fallback (capped) ───────────────────────
    rows = await db.ai_knowledge_base.find(
        {"tenant_id": tenant_id, "is_active": True,
          "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
        {"_id": 0},
    ).sort([("kind", 1), ("title", 1)]).to_list(500)
    if not rows:
        return "# Company knowledge\n\nNo company profile has been configured yet."

    sections = [header]
    running = len(header)
    hard_cap = 16_000   # ~4k tokens at the standard 4 chars/token estimate
    truncated = False
    for r in rows:
        chunk = f"\n## [{r.get('kind') or 'custom'}] {r.get('title') or ''}\n\n{r.get('content_md') or ''}"
        if running + len(chunk) > hard_cap:
            truncated = True
            break
        sections.append(chunk)
        running += len(chunk)
    logger.info(
        "[copilot-kb] fallback full-concat used tenant=%s rows=%d chars=%d cap=%d truncated=%s",
        tenant_id, len(rows), running, hard_cap, truncated,
    )
    return "\n".join(sections)


@router.get("/ai/knowledge/system-prompt", tags=["ai"],
             operation_id="ai.knowledge.systemPrompt")
async def get_system_prompt(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    q: Optional[str] = None,
):
    _require_admin(user)
    prompt = await _build_system_prompt(tenant["id"], query=q)
    # Phase P3 · Feb-2026 — Deliverable 1 · retrieval metadata for
    # the admin preview panel.  Only meaningful when ``?q=`` is set;
    # otherwise ``sources`` is [] and ``kb_row_count`` is the total
    # active KB row count so the panel can show "0 retrieved from N".
    sources: List[Dict[str, Any]] = []
    if q and q.strip():
        try:
            from services.ai_kb_retrieval import retrieve_kb_sources
            sources = await retrieve_kb_sources(tenant["id"], q.strip())
        except Exception as exc:                                     # noqa: BLE001
            logger.warning("[kb-preview] retriever failed: %s", exc)
            sources = []
    kb_row_count = await db.ai_knowledge_base.count_documents({
        "tenant_id": tenant["id"], "is_active": True,
        "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}],
    })
    return {
        "system_prompt": prompt,
        "retrieved": [
            {"id": s.get("doc_id"), "title": s.get("title"),
             "kind": s.get("kind"), "score": s.get("score")}
            for s in sources
        ],
        "retrieved_count": len(sources),
        "kb_row_count": kb_row_count,
        "query": q or "",
    }


# ══════════════════════════════════════════════════════════════
# Phase KB3 · Feb-2026 — File ingestion (PDF / DOCX / TXT / MD)
# ══════════════════════════════════════════════════════════════
#
# Real manuals go through the same S3 path used by
# ``customer_equipment`` photos (``services/file_storage.put_object``
# + a ``files`` row).  Extracted text lands in ``ai_knowledge_base.
# content_md`` so the existing ``retrieve_kb_sources`` picks it up
# automatically — no parallel index required.
_KB_FILE_MAX_BYTES = 25 * 1024 * 1024   # 25 MB (matches /api/files/upload)
_KB_FILE_MIN_TEXT = 20                   # chars

_KB_MIME_MAP: Dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
}
# Some browsers report ``application/msword`` for legacy .doc and
# ``application/octet-stream`` for .md — accept the extension fallback
# for the plain-text kinds only.
_KB_EXT_FALLBACK: Dict[str, str] = {
    "txt": "txt",
    "md": "md",
    "markdown": "md",
}


def _resolve_kb_source_type(
    content_type: str, filename: str,
) -> Optional[str]:
    """Return ``"pdf"|"docx"|"txt"|"md"`` or ``None`` when unsupported."""
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in _KB_MIME_MAP:
        return _KB_MIME_MAP[ct]
    # Extension fallback for the plain-text kinds only.
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    return _KB_EXT_FALLBACK.get(ext)


def _extract_pdf_text(data: bytes) -> str:
    """Concatenate every page's extracted text with a blank line
    between pages.  Returns "" on unrecoverable parse error."""
    from io import BytesIO
    try:
        from pypdf import PdfReader                              # noqa: WPS433
    except Exception:                                             # pragma: no cover
        return ""
    try:
        reader = PdfReader(BytesIO(data))
        pages_out: List[str] = []
        for page in reader.pages:
            try:
                pages_out.append((page.extract_text() or "").strip())
            except Exception:                                     # noqa: BLE001
                # Malformed page → skip it, keep going.
                pages_out.append("")
        return "\n\n".join(p for p in pages_out if p).strip()
    except Exception as exc:                                      # noqa: BLE001
        logger.warning("[kb-ingest] pdf parse failed: %s", exc)
        return ""


def _extract_docx_text(data: bytes) -> str:
    from io import BytesIO
    try:
        import docx                                               # noqa: WPS433
    except Exception:                                             # pragma: no cover
        return ""
    try:
        doc = docx.Document(BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if (p.text or "").strip()]
        return "\n\n".join(paragraphs).strip()
    except Exception as exc:                                      # noqa: BLE001
        logger.warning("[kb-ingest] docx parse failed: %s", exc)
        return ""


def _extract_text_plain(data: bytes) -> str:
    """Decode UTF-8, fall back to latin-1 with a debug log."""
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        logger.debug("[kb-ingest] utf-8 decode failed; using latin-1 fallback")
        try:
            return data.decode("latin-1", errors="replace").strip()
        except Exception:                                         # noqa: BLE001
            return ""


def _extract_kb_text(source_type: str, data: bytes) -> str:
    if source_type == "pdf":
        return _extract_pdf_text(data)
    if source_type == "docx":
        return _extract_docx_text(data)
    if source_type in ("txt", "md"):
        return _extract_text_plain(data)
    return ""


@router.post("/ai/knowledge/file",
              tags=["ai"], operation_id="ai.knowledge.fileIngest")
async def ingest_knowledge_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    kind: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Upload PDF / DOCX / TXT / MD → S3 + parse → insert into
    ``ai_knowledge_base``.  Admin only (mirrors the other /ai/knowledge
    endpoints).  Text ends up in ``content_md`` so the existing
    retriever indexes it automatically.
    """
    # Runtime import to keep the ``file_storage`` boot side-effect
    # (S3 session client) out of module import; tests can inject
    # their own stubs without triggering it.
    from services.file_storage import (                           # noqa: WPS433
        APP_NAME, StorageError, is_storage_configured, put_object,
    )

    _require_admin(user)

    # Feb-2026 · Ticket #4 · AI Configuration org toggle. Admin
    # can hard-disable KB uploads from Org Settings → AI
    # Configuration. Reject with a clean 403 + typed error code
    # so the client can surface a targeted message.
    _ai_settings = (tenant.get("settings") or {}).get("ai") or {}
    if _ai_settings.get("kb_uploads_enabled") is False:
        raise HTTPException(403, {
            "code": "kb_uploads_disabled_by_org",
            "message": "Knowledge Base uploads are disabled for this organization.",
        })

    if file is None:
        raise HTTPException(400, "file is required")

    # ── Size + content-type gates ──────────────────────────────────
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    source_type = _resolve_kb_source_type(content_type, file.filename or "")
    if not source_type:
        raise HTTPException(415, {
            "code": "unsupported_media_type",
            "message": (
                f"Content type {content_type!r} is not accepted. "
                "Allowed: PDF, DOCX, TXT, MD."
            ),
        })

    data = await file.read()
    if not data:
        raise HTTPException(400, "empty_file")
    if len(data) > _KB_FILE_MAX_BYTES:
        raise HTTPException(413, {
            "code": "file_too_large",
            "message": f"Max upload size is {_KB_FILE_MAX_BYTES} bytes (25 MB).",
        })

    # ── Extract text BEFORE spending S3 write cost so an empty
    #    extraction fast-fails without leaving a dangling object.
    extracted = _extract_kb_text(source_type, data)
    if len(extracted) < _KB_FILE_MIN_TEXT:
        raise HTTPException(400, {
            "code": "extraction_empty",
            "message": (
                "No extractable text was found in the uploaded file. "
                "If this is a scanned document, run OCR first and "
                "re-upload the text-layer PDF."
            ),
            "chars_extracted": len(extracted),
        })

    # ── Upload the ORIGINAL binary to S3 (same primitive as
    #    customer_equipment photos + /api/files/upload). ────────────
    if not is_storage_configured():
        raise HTTPException(503, {
            "code": "storage_unavailable",
            "message": "File storage is not configured on this server.",
        })
    import uuid
    ext = source_type
    fname = f"{uuid.uuid4().hex}.{ext}"
    tenant_seg = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (tenant["id"] or "unknown")
    )[:64] or "unknown"
    path = "/".join([APP_NAME, tenant_seg, "ai-knowledge", fname])
    try:
        meta = put_object(path, data, content_type or "application/octet-stream")
    except StorageError as exc:
        logger.warning("[kb-ingest] put_object failed: %s", exc)
        raise HTTPException(502, {
            "code": "storage_write_failed",
            "message": str(exc),
        })

    file_id = new_id()
    files_doc = {
        "id": file_id,
        "tenant_id": tenant["id"],
        "storage_path": meta["path"],
        "storage": "s3",
        "original_filename": file.filename or fname,
        "content_type": content_type or "application/octet-stream",
        "size": int(meta.get("size") or len(data)),
        "uploaded_by_user_id": user.get("id"),
        "purpose": "ai-knowledge",
        "linked_entity_type": "ai_knowledge_base",
        "linked_entity_id": None,                                 # backfilled after KB row insert
        "created_at": now_iso(),
        "is_deleted": False,
        "deleted_at": None,
    }
    await db.files.insert_one(files_doc)

    # ── Build content_md.  For PDFs that look tabular (many short
    #    lines) we wrap in a fenced block so the LLM preserves
    #    columns — best-effort, not exact. ──────────────────────────
    content_md = extracted
    if source_type == "pdf":
        lines = extracted.splitlines()
        short_lines = sum(1 for line in lines if 0 < len(line.strip()) <= 40)
        if lines and short_lines / max(len(lines), 1) > 0.5:
            content_md = "```\n" + extracted + "\n```"

    # ── Insert the knowledge base row. ─────────────────────────────
    parsed_tags: List[str] = []
    if tags:
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    resolved_kind = (kind or "custom").strip()
    if resolved_kind not in _KIND_VALUES:
        resolved_kind = "custom"
    resolved_title = (title or "").strip()
    if not resolved_title:
        base = (file.filename or fname)
        # Strip extension for a friendly default.
        resolved_title = base.rsplit(".", 1)[0] if "." in base else base
    resolved_title = resolved_title[:200]

    kb_id = new_id()
    kb_doc = {
        "id": kb_id,
        "tenant_id": tenant["id"],
        "kind": resolved_kind,
        "title": resolved_title,
        "content_md": content_md,
        "tags": parsed_tags,
        "is_active": True,
        "source_type": source_type,
        "source_file_id": file_id,
        "created_by": user.get("id"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.ai_knowledge_base.insert_one(kb_doc)

    # Backfill linked_entity_id on the files row so a future
    # /api/files listing lands the file under its KB row.
    await db.files.update_one(
        {"id": file_id},
        {"$set": {"linked_entity_id": kb_id}},
    )

    logger.info(
        "[kb-ingest] tenant=%s kb_id=%s file_id=%s source=%s size=%d chars=%d",
        tenant["id"], kb_id, file_id, source_type, len(data), len(content_md),
    )

    kb_doc.pop("_id", None)
    return {
        "kb": kb_doc,
        "file": {
            "id": file_id,
            "url": f"/api/files/{file_id}/download",
            "original_filename": files_doc["original_filename"],
            "content_type": files_doc["content_type"],
            "size": files_doc["size"],
        },
    }


# ══════════════════════════════════════════════════════════════
# Copilot — read-only chat with tenant-scoped tools
# ══════════════════════════════════════════════════════════════
class CopilotMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    thread_id: Optional[str] = None


async def _tool_list_customers(tenant_id: str, query: str = "") -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                          "$or": [{"is_deleted": {"$ne": True}},
                                    {"is_deleted": {"$exists": False}}]}
    if query:
        q["$and"] = [{"$or": [
            {"name": {"$regex": query, "$options": "i"}},
            {"email": {"$regex": query, "$options": "i"}},
            {"phone": {"$regex": query, "$options": "i"}},
            {"service_address": {"$regex": query, "$options": "i"}},
        ]}]
    rows = await db.customers.find(q, {
        "_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
        "service_address": 1, "tags": 1, "category_ids": 1,
        "is_active": 1,
    }).limit(20).to_list(20)
    return rows


async def _tool_get_customer(tenant_id: str, customer_id: str) -> Dict[str, Any]:
    """CRITICAL: tenant_id is auto-injected — the LLM cannot pierce
    the tenant boundary even if it hallucinates a customer_id from
    another tenant."""
    c = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not c:
        return {"error": "not_found",
                 "message": "No customer with that id in this tenant."}
    comms = await db.marketing_deliveries.find(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0, "channel": 1, "subject": 1, "created_at": 1,
          "delivered": 1, "trigger_entity": 1},
    ).sort("created_at", -1).limit(10).to_list(10)
    from utils import not_deleted_filter as _nd
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id, "customer_id": customer_id, **_nd()},
        {"_id": 0, "id": 1, "scheduled_date": 1, "status": 1,
          "service_type": 1},
    ).sort("scheduled_date", -1).limit(10).to_list(10)
    return {"customer": c, "recent_comms": comms, "recent_jobs": jobs}


async def _tool_revenue_forecast(tenant_id: str, range_: str = "week") -> Dict[str, Any]:
    from routers.reports import _forecast_series_between  # local import
    from datetime import date, timedelta
    tz_name = "America/Phoenix"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    today = datetime.now(tz).date()
    if range_ == "today":
        start, end = today, today
    elif range_ == "tomorrow":
        start = today + timedelta(days=1); end = start
    elif range_ == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    else:  # month
        start = today.replace(day=1)
        end = (start.replace(month=start.month + 1) if start.month < 12
                else start.replace(year=start.year + 1, month=1)) - timedelta(days=1)
    series = await _forecast_series_between(start, end)
    return {"range": range_, "date_from": start.isoformat(),
             "date_to": end.isoformat(),
             "total": round(sum(x["amount"] for x in series), 2),
             "series": series}


async def _tool_list_leads(tenant_id: str, status: str = "new",
                            limit: int = 20) -> List[Dict[str, Any]]:
    q = {"tenant_id": tenant_id}
    if status and status != "all":
        q["status"] = status
    return await db.leads.find(
        q, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
             "status": 1, "created_at": 1, "state": 1, "city": 1,
             "rejected_reason": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)


async def _tool_list_jobs(tenant_id: str, day: Optional[str] = None,
                           tech_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if day:
        q["scheduled_date"] = {"$regex": f"^{day}"}
    if tech_id:
        q["technician_id"] = tech_id
    return await db.jobs.find(
        q, {"_id": 0, "id": 1, "customer_id": 1, "technician_id": 1,
             "scheduled_date": 1, "scheduled_start_at": 1, "status": 1,
             "service_type": 1},
    ).sort("scheduled_date", -1).limit(50).to_list(50)


async def _tool_communications_log(tenant_id: str, customer_id: Optional[str] = None,
                                     since: Optional[str] = None,
                                     limit: int = 30) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_id:
        q["customer_id"] = customer_id
    if since:
        q["created_at"] = {"$gte": since}
    return await db.marketing_deliveries.find(
        q, {"_id": 0, "channel": 1, "customer_id": 1, "subject": 1,
             "body": 1, "created_at": 1, "delivered": 1,
             "trigger_entity": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)


_TOOLS = {
    "list_customers":       ("List customers matching a name/email/phone/address search.",
                              _tool_list_customers, ["query"]),
    "get_customer":         ("Get a customer's full profile plus last 10 comms + last 10 jobs.",
                              _tool_get_customer,   ["customer_id"]),
    "revenue_forecast":     ("Get revenue forecast for a range: today/tomorrow/week/month.",
                              _tool_revenue_forecast, ["range"]),
    "list_leads":           ("List leads by status (new/contacted/qualified/converted/rejected).",
                              _tool_list_leads,     ["status", "limit"]),
    "list_jobs":            ("List scheduled jobs, optionally filtered by day (YYYY-MM-DD) or tech id.",
                              _tool_list_jobs,      ["day", "tech_id"]),
    "communications_log":   ("List recent SMS/email deliveries, optionally filtered by customer.",
                              _tool_communications_log, ["customer_id", "since", "limit"]),
}


def _tool_schema_markdown() -> str:
    lines = ["# TOOLS (read-only — tenant_id auto-injected)"]
    for name, (desc, _, params) in _TOOLS.items():
        lines.append(f"- **{name}**({', '.join(params)}): {desc}")
    lines.append(
        "\nWhen you want to call a tool, respond with a JSON code "
        'fence like:\n```tool\n{"name":"list_customers","args":{"query":"garcia"}}\n```\n'
        "The system will substitute the tool output and continue."
    )
    return "\n".join(lines)


async def _run_tool(tenant_id: str, name: str, args: Dict[str, Any]) -> Any:
    spec = _TOOLS.get(name)
    if not spec:
        return {"error": "unknown_tool", "tool": name}
    _desc, fn, _params = spec
    try:
        # Sanitize args — silently drop unexpected keys + coerce simple types.
        clean = {k: v for k, v in (args or {}).items() if isinstance(k, str)}
        if name == "revenue_forecast":
            return await fn(tenant_id, range_=clean.get("range", "week"))
        # Everything else takes ``tenant_id`` first + kwargs.
        return await fn(tenant_id, **clean)
    except TypeError as exc:
        return {"error": "bad_args", "detail": str(exc)}
    except Exception as exc:
        logger.warning("[copilot] tool %s failed: %s", name, exc)
        return {"error": "tool_failed", "detail": str(exc)}


@router.post("/ai/copilot/message", tags=["ai"], operation_id="ai.copilot.message")
async def copilot_message(
    body: CopilotMessageIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    thread_id = body.thread_id or new_id()

    # Phase KB2 · Feb-2026 — pass the user's message as the retrieval
    # query so the shared top-5 RAG kicks in instead of the old
    # full-KB concat.
    system_prompt = await _build_system_prompt(tenant["id"], query=body.message)
    system_prompt += "\n\n" + _tool_schema_markdown()

    tool_calls: List[Dict[str, Any]] = []
    reply_text = ""
    tokens_used = 0

    # Import the Emergent LLM client. If unavailable (offline sandbox
    # or key not provisioned) we degrade to a canned response so the
    # UI + audit log flow still work — pytest can mock this path.
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply. The SDK-native ``chat`` session preserved
        # multi-turn context automatically; the chokepoint creates a
        # new session per call, so the tool-call loop below rebuilds
        # the running transcript in ``combined`` before every call.
        # Observable behavior is identical: same tool fences parsed,
        # same tool executed, same follow-up message shape.
        from services.llm_provider import call_llm_with_fallback  # type: ignore
        from services.ai.cap_http import is_ai_cap_exceeded  # type: ignore
        emergent_key = os.environ.get("EMERGENT_LLM_KEY") or ""
        if not emergent_key:
            raise RuntimeError("EMERGENT_LLM_KEY not set")

        async def _turn(prompt: str) -> str:
            _r = await call_llm_with_fallback(
                system_prompt=system_prompt, user_text=prompt,
                provider="anthropic", model="claude-sonnet-4-5",
                tenant_id=tenant["id"],
                parse_json=False,
            )
            if is_ai_cap_exceeded(_r):
                raise RuntimeError("ai_spend_cap_exceeded")
            if _r.get("error"):
                raise RuntimeError(str(_r.get("error")))
            return ((_r.get("raw") or {}).get("text") or "").strip()

        transcript = f"[user] {body.message}"
        cur = await _turn(transcript)
        # Basic tool-call loop — up to 3 rounds. Frontier LLMs almost
        # never need more than 2 in this Copilot's read-only shape.
        for _ in range(3):
            # Look for a ```tool ...``` fence.
            fence_open = cur.find("```tool")
            if fence_open < 0:
                break
            fence_close = cur.find("```", fence_open + 7)
            if fence_close < 0:
                break
            raw_tool = cur[fence_open + 7:fence_close].strip()
            try:
                call = json.loads(raw_tool)
            except Exception:
                break
            tname = str(call.get("name") or "")
            targs = call.get("args") or {}
            result = await _run_tool(tenant["id"], tname, targs)
            tool_calls.append({"name": tname, "args": targs,
                                "result_preview": str(result)[:400]})
            follow = f"Tool `{tname}` returned:\n```json\n{json.dumps(result, default=str)[:4000]}\n```"
            transcript += f"\n[assistant] {cur}\n[user] {follow}"
            cur = await _turn(transcript)
        reply_text = str(cur)
    except Exception as exc:
        logger.warning("[copilot] LLM path failed: %s", exc)
        reply_text = ("The Copilot's LLM backend isn't reachable right now. "
                       "Your message was recorded. Try again in a moment.")

    log_row = {
        "id": new_id(), "tenant_id": tenant["id"],
        "user_id": user.get("id"), "thread_id": thread_id,
        "prompt": body.message, "response": reply_text,
        "tool_calls": tool_calls, "tokens_used": tokens_used,
        "created_at": now_iso(),
    }
    await db.ai_copilot_log.insert_one(log_row)
    log_row.pop("_id", None)
    return {"thread_id": thread_id, "reply": reply_text,
             "tool_calls": tool_calls}


# ══════════════════════════════════════════════════════════════
# Feb-2026 · Item 4 bonus — Top admin questions widget.
# Groups ai_copilot_log entries by prompt (case-insensitive) over
# the last N days and returns the most frequently asked questions.
# Powers the AI Brain page dashboard so admins can quickly promote
# common Copilot prompts into their knowledge base.
# ══════════════════════════════════════════════════════════════
@router.get("/ai/copilot/top-questions", tags=["ai"],
             operation_id="ai.copilot.topQuestions")
async def top_questions(
    days: int = 30,
    limit: int = 10,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 10), 50))
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"tenant_id": tenant["id"], "created_at": {"$gte": since},
                     "prompt": {"$exists": True, "$ne": ""}}},
        # Normalize (lowercase + trim) so "How many customers?" and
        # "how many customers?  " group together.
        {"$addFields": {"_norm": {"$toLower": {"$trim": {"input": "$prompt"}}}}},
        {"$group": {
            "_id": "$_norm",
            "count": {"$sum": 1},
            "last_prompt": {"$last": "$prompt"},
            "last_response": {"$last": "$response"},
            "last_asked_at": {"$max": "$created_at"},
        }},
        {"$sort": {"count": -1, "last_asked_at": -1}},
        {"$limit": limit},
    ]
    rows = await db.ai_copilot_log.aggregate(pipeline).to_list(limit)
    return {
        "days": days,
        "total": len(rows),
        "items": [
            {"prompt": r.get("last_prompt") or r.get("_id"),
             "count": int(r.get("count") or 0),
             "last_asked_at": r.get("last_asked_at"),
             "last_response": (r.get("last_response") or "")[:400]}
            for r in rows
        ],
    }



# ══════════════════════════════════════════════════════════════
# Feb-2026 · Phase 20 P2 — Admin toggle for the daily review digest.
# Persists to ``tenants.settings.daily_review_digest_enabled``.
# ══════════════════════════════════════════════════════════════
class DigestToggleIn(BaseModel):
    enabled: bool


@router.get("/ai/settings/daily-review-digest", tags=["ai"],
             operation_id="ai.settings.dailyReviewDigest.get")
async def get_digest_toggle(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    settings = (tenant or {}).get("settings") or {}
    enabled = settings.get("daily_review_digest_enabled")
    # Default is True — the cron opts you IN unless you explicitly
    # opt out.
    return {"enabled": True if enabled is None else bool(enabled)}


@router.patch("/ai/settings/daily-review-digest", tags=["ai"],
               operation_id="ai.settings.dailyReviewDigest.patch")
async def patch_digest_toggle(
    body: DigestToggleIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.daily_review_digest_enabled": bool(body.enabled)}},
    )
    return {"ok": True, "enabled": bool(body.enabled)}


# ═════════════════════════════════════════════════════════════
# Feb-2026 · smart enhancement — Weekly AI Employees Summary tile.
# 5-minute per-tenant in-memory cache; bust via ``?refresh=1``.
# ═════════════════════════════════════════════════════════════
import time as _time
from datetime import timedelta as _td

_WEEKLY_CACHE: dict = {}
_WEEKLY_TTL_S = 300


@router.get("/ai/employees/weekly-summary", tags=["ai"],
             operation_id="ai.employees.weeklySummary")
async def weekly_ai_employees_summary(
    refresh: int = 0,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    ck = f"weekly:{tid}"
    if not refresh:
        cached = _WEEKLY_CACHE.get(ck)
        if cached and (_time.time() - cached["_at"]) < _WEEKLY_TTL_S:
            return cached["payload"]

    now = datetime.now(timezone.utc)
    week_start = now - _td(days=7)
    prev_start = now - _td(days=14)
    prev_end = now - _td(days=7)

    drafts = await db.gbp_post_drafts.count_documents({
        "tenant_id": tid,
        "generated_at": {"$gte": week_start.isoformat()},
    })

    reviews_answered = await db.reviews.count_documents({
        "tenant_id": tid,
        "$or": [
            {"suggested_reply_generated_at": {"$gte": week_start.isoformat()}},
            {"admin_replied_at": {"$gte": week_start.isoformat()}},
        ],
    })

    scan = await db.seo_scans.find_one(
        {"tenant_id": tid}, {"_id": 0, "score": 1},
        sort=[("run_at", -1)],
    )
    seo_score_latest = int((scan or {}).get("score")) if scan else None

    async def _avg(start_iso, end_iso):
        pipe = [
            {"$match": {"tenant_id": tid,
                         "created_at": {"$gte": start_iso, "$lt": end_iso},
                         "star_rating": {"$gte": 1, "$lte": 5}}},
            {"$group": {"_id": None, "count": {"$sum": 1},
                         "avg": {"$avg": "$star_rating"}}},
        ]
        rows = await db.reviews.aggregate(pipe).to_list(1)
        if not rows:
            return 0, 0.0
        return int(rows[0].get("count") or 0), float(rows[0].get("avg") or 0.0)

    this_count, this_avg = await _avg(week_start.isoformat(), now.isoformat())
    _prev_count, prev_avg = await _avg(prev_start.isoformat(), prev_end.isoformat())
    if this_count and _prev_count:
        star_delta = round(this_avg - prev_avg, 2)
    else:
        star_delta = None

    payload = {
        "tenant_id": tid,
        "week_start_at": week_start.isoformat(),
        "week_end_at": now.isoformat(),
        "drafts_generated": int(drafts),
        "reviews_answered": int(reviews_answered),
        "seo_score_latest": seo_score_latest,
        "star_delta": star_delta,
        "total_reviews_last_week": this_count,
        "generated_at": now.isoformat(),
    }
    _WEEKLY_CACHE[ck] = {"_at": _time.time(), "payload": payload}
    return payload
