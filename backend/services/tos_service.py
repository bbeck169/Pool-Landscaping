"""Feb-2026 · Slice 2A — Multi-ToS Backend Foundation.

Shared helpers for the Pool / Landscaping split of the Terms-of-
Service system. Responsibilities:

* :func:`sanitize_html` — server-side bleach allow-list for content
  arriving from the admin TipTap editor. Anything outside the
  allow-list is stripped (not escaped) so the resulting HTML is
  safe to embed inside a customer-portal modal.
* :func:`classify_customer_services` — decides which ToS documents a
  customer must accept, driven by the ``service_type`` on the
  customer + their active jobs + active recurring subscriptions.
* :func:`current_published_docs` — returns the currently published
  ToS document per service_type for a tenant. Used both by the
  customer onboarding-state endpoint and the notification-blast
  worker in Slice 2D.
* :func:`compute_pending_tos_for_customer` — the primary customer
  helper. Returns the list of documents the customer still needs to
  accept, in the canonical (pool → landscaping) order.
* :func:`record_customer_acceptance` — atomically writes both the
  ``tos_acceptances`` audit row AND updates
  ``customer.tos_status.{service_type}``.
* :func:`seed_pool_tos_from_legacy` — one-shot boot migration. If a
  tenant has no ``tos_documents`` rows for ``service_type=pool``,
  copy the legacy ``config_tos.TOS_MARKDOWN`` into a new
  ``published`` v1 document (markdown wrapped in ``<pre>``).
* :func:`publish_document` — draft → published transition with
  atomic supersede-of-prior-published-row. Legal audit trail
  invariant: NEVER hard-delete a published document.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

import bleach

# Public constants — used by tests + the admin router.
SERVICE_TYPES = ("pool", "landscaping")
DOC_STATUSES = ("draft", "published", "superseded")

# ── Sanitizer allow-list ─────────────────────────────────────────────
# Kept narrow on purpose: TipTap's default marks + a few list/heading
# constructs, plus ``<pre>`` for pasted plain-text ToS blobs. No
# ``<script>``, no ``<style>``, no ``<iframe>``, no ``<object>``.
_ALLOWED_TAGS = frozenset({
    "p", "br", "strong", "em", "u", "s", "code",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "blockquote",
    "pre",
    "a",
    "hr",
    "table", "thead", "tbody", "tr", "th", "td",
})
_ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}
_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto", "tel"})


def sanitize_html(raw: Optional[str]) -> str:
    """Strip anything outside the TipTap allow-list.

    Uses ``strip=True`` so disallowed tags are removed (not escaped)
    — legal text should render as legal text. Passing ``None`` or an
    empty string returns ``""``. External links are silently
    stamped with ``rel="noopener noreferrer"`` and ``target="_blank"``
    so the customer's portal session is protected.
    """
    if not raw:
        return ""
    cleaned = bleach.clean(
        raw,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Harden external anchors: always add rel="noopener noreferrer"
    # + target="_blank". Uses a lightweight regex — bleach's
    # ``LinkifyFilter`` would be heavier and pull in tldextract.
    def _harden(m: re.Match) -> str:
        attrs = m.group(1) or ""
        if "target=" not in attrs:
            attrs = f'{attrs} target="_blank"'
        if "rel=" not in attrs:
            attrs = f'{attrs} rel="noopener noreferrer"'
        return f"<a{attrs}>"
    return re.sub(
        r'<a((?:\s+[^>]*)?)>', _harden, cleaned,
    )


# ── Service-type classification ─────────────────────────────────────
def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def _service_type_from_string(s: str) -> Optional[str]:
    """Map a free-form ``service_type`` string to one of
    ``SERVICE_TYPES``. Returns ``None`` for unmatched strings.
    """
    n = _norm(s)
    if not n:
        return None
    if "pool" in n or "spa" in n or "chem" in n:
        return "pool"
    if ("landscap" in n or "lawn" in n or "yard" in n or "garden" in n
        or "irrig" in n or "tree" in n or "shrub" in n
        or "mow" in n or "hedge" in n):
        return "landscaping"
    return None


async def classify_customer_services(
    db, tenant_id: str, customer: Dict[str, Any],
) -> Set[str]:
    """Return the set of ``SERVICE_TYPES`` the customer is enrolled in.

    Signals (union'd):
      * ``customer.service_type`` — the legacy free-form field.
      * ``customer.service_types`` — optional explicit list of the
        two canonical values.
      * Active jobs — any job with ``status != "completed"`` and
        ``customer_id == cid`` contributes its ``service_type``.
      * Active recurring subscriptions on the customer.
    """
    out: Set[str] = set()
    cid = customer.get("id") if customer else None
    # 1) Explicit list wins.
    explicit = customer.get("service_types") if customer else None
    if isinstance(explicit, (list, tuple, set)):
        for s in explicit:
            n = _norm(s)
            if n in SERVICE_TYPES:
                out.add(n)
    # 2) Legacy string field.
    st = _service_type_from_string(
        (customer or {}).get("service_type") or "",
    )
    if st:
        out.add(st)
    # 3) Active jobs.
    if cid and db is not None:
        async for job in db.jobs.find(
            {"tenant_id": tenant_id, "customer_id": cid,
             "status": {"$nin": ["completed", "cancelled", "archived"]}},
            {"_id": 0, "service_type": 1},
        ):
            sj = _service_type_from_string(job.get("service_type") or "")
            if sj:
                out.add(sj)
    # 4) Active recurring subscriptions.
    if cid and db is not None:
        async for sub in db.recurring_subscriptions.find(
            {"tenant_id": tenant_id, "customer_id": cid,
             "active": True},
            {"_id": 0, "service_type": 1},
        ):
            ss = _service_type_from_string(sub.get("service_type") or "")
            if ss:
                out.add(ss)
    return out


# ── Documents ────────────────────────────────────────────────────────
async def current_published_docs(
    db, tenant_id: str,
) -> Dict[str, Dict[str, Any]]:
    """Map ``service_type -> latest published document`` for the
    tenant. Missing service_type key means no published doc yet.
    """
    cursor = db.tos_documents.find(
        {"tenant_id": tenant_id, "status": "published"},
        {"_id": 0},
    )
    docs = await cursor.to_list(length=100)
    out: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        s = d.get("service_type")
        if s not in SERVICE_TYPES:
            continue
        # Highest version wins if multiple published rows sneak in
        # (shouldn't happen — supersede is atomic — but be defensive).
        existing = out.get(s)
        if not existing or int(d.get("version", 0)) > int(
            existing.get("version", 0),
        ):
            out[s] = d
    return out


def _has_accepted(
    customer: Dict[str, Any], service_type: str, doc: Dict[str, Any],
) -> bool:
    """``True`` iff the customer's embedded ``tos_status`` records an
    acceptance for the currently published version.
    """
    ts = (customer or {}).get("tos_status") or {}
    entry = ts.get(service_type) or {}
    return int(entry.get("version") or 0) >= int(doc.get("version") or 0)


async def compute_pending_tos_for_customer(
    db, tenant_id: str, customer: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return the ordered list of ToS documents the customer still
    needs to accept. Order is canonical: pool first, then landscaping.

    Each entry is a lightweight DTO safe for a customer-facing
    endpoint: ``document_id``, ``service_type``, ``version``,
    ``title``, ``content_html``, ``effective_date``.
    """
    services = await classify_customer_services(db, tenant_id, customer)
    if not services:
        return []
    published = await current_published_docs(db, tenant_id)
    pending: List[Dict[str, Any]] = []
    for s in SERVICE_TYPES:
        if s not in services:
            continue
        doc = published.get(s)
        if not doc:
            continue
        if _has_accepted(customer, s, doc):
            continue
        pending.append({
            "document_id": doc["id"],
            "service_type": s,
            "version": int(doc.get("version") or 1),
            "title": doc.get("title") or "",
            "content_html": doc.get("content_html") or "",
            "effective_date": doc.get("effective_date"),
        })
    return pending


# ── Acceptance ───────────────────────────────────────────────────────
async def record_customer_acceptance(
    db, *, tenant_id: str, customer_id: str, document_id: str,
    ip: Optional[str] = None, ua: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically stamp an acceptance row + update the customer's
    embedded ``tos_status.{service_type}`` map so the next
    ``compute_pending_tos_for_customer`` call returns one fewer item.

    Returns the created acceptance row (safe DTO). Raises
    ``ValueError`` if the document doesn't exist or isn't published.
    """
    doc = await db.tos_documents.find_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not doc:
        raise ValueError("document_not_found")
    if doc.get("status") != "published":
        raise ValueError("document_not_published")
    service_type = doc.get("service_type")
    if service_type not in SERVICE_TYPES:
        raise ValueError("document_service_type_invalid")

    now = datetime.now(timezone.utc).isoformat()
    from utils import new_id
    accept_row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "document_id": document_id,
        "service_type": service_type,
        "document_version": int(doc.get("version") or 1),
        "accepted_at": now,
        "ip": ip, "ua": ua,
    }
    await db.tos_acceptances.insert_one(accept_row)
    accept_row.pop("_id", None)  # ObjectId — never leak out.
    await db.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$set": {f"tos_status.{service_type}": {
            "document_id": document_id,
            "version": int(doc.get("version") or 1),
            "accepted_at": now,
        }}},
    )
    return accept_row


# ── Publish / supersede ─────────────────────────────────────────────
async def publish_document(
    db, *, tenant_id: str, document_id: str, actor_id: str,
) -> Dict[str, Any]:
    """Transition a draft to ``published``. In the same call, any
    previously ``published`` row for the same ``(tenant_id,
    service_type)`` is atomically marked ``superseded``.

    Legal audit trail invariant: superseded rows are NEVER deleted.
    Returns the freshly published document.
    """
    doc = await db.tos_documents.find_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not doc:
        raise ValueError("document_not_found")
    if doc.get("status") == "published":
        return doc  # idempotent
    if doc.get("status") == "superseded":
        raise ValueError("document_already_superseded")

    service_type = doc.get("service_type")
    if service_type not in SERVICE_TYPES:
        raise ValueError("service_type_invalid")

    now = datetime.now(timezone.utc).isoformat()
    # 1) Supersede prior published row (if any).
    await db.tos_documents.update_many(
        {"tenant_id": tenant_id, "service_type": service_type,
         "status": "published"},
        {"$set": {"status": "superseded", "superseded_at": now}},
    )
    # 2) Promote this draft.
    await db.tos_documents.update_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"$set": {
            "status": "published",
            "published_at": now,
            "published_by": actor_id,
        }},
    )
    fresh = await db.tos_documents.find_one(
        {"id": document_id, "tenant_id": tenant_id},
        {"_id": 0},
    ) or doc
    return fresh


async def next_version_for(
    db, tenant_id: str, service_type: str,
) -> int:
    """Monotonically-increasing per (tenant, service_type)."""
    top = await db.tos_documents.find_one(
        {"tenant_id": tenant_id, "service_type": service_type},
        {"_id": 0, "version": 1},
        sort=[("version", -1)],
    )
    return int((top or {}).get("version") or 0) + 1


# ── Seed / migration ────────────────────────────────────────────────
async def seed_pool_tos_from_legacy(
    db, tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """One-shot backfill — if a tenant has no ``tos_documents`` rows
    for ``service_type=pool``, create v1 from the legacy
    ``config_tos.TOS_MARKDOWN`` blob and publish it. Idempotent — a
    second run with existing pool rows is a no-op.
    """
    existing = await db.tos_documents.find_one(
        {"tenant_id": tenant_id, "service_type": "pool"},
        {"_id": 0, "id": 1},
    )
    if existing:
        return None
    from config_tos import (
        TOS_MARKDOWN,
        CURRENT_TOS_VERSION,
        CURRENT_TOS_EFFECTIVE_DATE,
    )
    from utils import new_id
    now = datetime.now(timezone.utc).isoformat()
    # Legacy content is markdown — wrap in <pre> so the customer's
    # portal renders it monospaced but readable until the admin
    # migrates the copy to TipTap-rendered HTML.
    body = (
        "<h2>Pool &amp; Landscaping of Vistancia — Terms of Service</h2>"
        f"<p><em>Version {CURRENT_TOS_VERSION} — "
        f"Effective {CURRENT_TOS_EFFECTIVE_DATE}</em></p>"
        f"<pre>{bleach.clean(TOS_MARKDOWN, tags=set(), strip=False)}</pre>"
    )
    row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "service_type": "pool",
        "version": 1,
        "status": "published",
        "title": "Pool Services — Terms of Service",
        "content_html": body,
        "content_json": None,
        "effective_date": CURRENT_TOS_EFFECTIVE_DATE,
        "created_at": now,
        "created_by": "system_seed",
        "published_at": now,
        "published_by": "system_seed",
        "superseded_at": None,
    }
    await db.tos_documents.insert_one(row)
    row.pop("_id", None)  # ObjectId — never leak out.
    return row


# ── Indexes ──────────────────────────────────────────────────────────
async def ensure_indexes(db) -> None:
    """Idempotent index creation for the Multi-ToS collections."""
    await db.tos_documents.create_index(
        [("tenant_id", 1), ("service_type", 1), ("version", -1)],
    )
    await db.tos_documents.create_index(
        [("tenant_id", 1), ("service_type", 1), ("status", 1)],
    )
    await db.tos_acceptances.create_index(
        [("tenant_id", 1), ("customer_id", 1), ("document_id", 1)],
        unique=True,
    )
    await db.tos_acceptances.create_index(
        [("tenant_id", 1), ("customer_id", 1)],
    )
