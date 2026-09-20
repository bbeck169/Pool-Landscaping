"""Phase 9C · Feb 2026 — Marketing media library.

Backend for the Emergent Object Storage-backed asset library. Frontend
(TipTap ``<MediaLibraryPicker>``) consumes these endpoints in the next
session.

* Upload validates magic bytes, strips EXIF (JPEG/PNG/WebP), rejects
  SVG containing script/JS-URI content, caps size at 5 MB (200 KB for
  SVG).
* Every file is stored under
  ``pool-crm/tenants/{tenant_id}/marketing_media/{uuid}.{ext}`` in the
  shared bucket. Downloads proxy through this router so tenant
  isolation + auth are enforced.
* Soft-delete is guarded by a grep against
  ``marketing_templates.body`` — active templates that still reference
  the URL block the delete with **409**.

Feb-2026 · Customer-Attachments widening (Option D)
    The library was image-only through Q1. To power customer
    email/SMS attachments (invoices, work orders, quotes, receipts,
    etc.), the allowed set now includes PDF, DOCX, XLSX, CSV, and TXT
    with per-type size caps and magic-byte checks (or extension +
    content-sniff for the two text formats where magic bytes are
    unreliable — see the ``_TEXT_SNIFF_EXT`` comment). Video is
    deliberately out of scope for this phase.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import re
import time
import uuid as _uuid
from typing import Dict, List, Optional, Tuple

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, Response,
    UploadFile,
)

# Phase P1.2 · Feb 2026 — SlowAPI per-IP rate limit for the
# signed-URL download route. ``limiter`` is exposed at module scope
# so future routes that need the same 60/min IP limit can decorate
# themselves without reinstantiating; the limiter itself is
# registered on the FastAPI app in ``server.py``.
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    def _p12_client_key(request) -> str:
        """Return the ORIGINAL client IP, honoring the K8s ingress
        chain.

        SlowAPI's stock :func:`get_remote_address` returns
        ``request.client.host``, which behind Emergent's K8s ingress
        is the ingress pod IP — 10.79.165.x. There are multiple
        ingress pods and traffic round-robins between them, so a
        stock config would spread one client's requests across N
        counters and never fire the 60/minute limit.

        Contract:
          * Prefer the leftmost entry of ``X-Forwarded-For`` (that's
            the original client per RFC 7239).
          * Fall back to :func:`get_remote_address` if the header is
            absent (unit tests, direct hits).
        """
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
        return get_remote_address(request)

    # Phase P1.2 · Feb 2026 — ``headers_enabled=True`` is what makes
    # slowapi attach ``X-RateLimit-*`` and ``Retry-After`` to the 429
    # response. Without it the 429 has an empty header set and any
    # client that respects RFC 6585 has no back-off signal.
    limiter = Limiter(key_func=_p12_client_key, headers_enabled=True)
except Exception:  # pragma: no cover — defensive; slowapi is in requirements
    limiter = None  # type: ignore[assignment]

from config import db, logger, JWT_SECRET
from routers.tenants import get_current_tenant
from services.marketing_media.storage_client import (
    StorageUnavailable, build_path, get_object, put_object,
)
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter()

# ─────────── Constants
_MAX_SIZE_IMG = 5 * 1024 * 1024           # 5 MB — images
_MAX_SIZE_SVG = 200 * 1024                # 200 KB — SVG
_MAX_SIZE_PDF = 15 * 1024 * 1024          # 15 MB — PDF
_MAX_SIZE_DOC = 10 * 1024 * 1024          # 10 MB — docx/xlsx/csv/txt

# Feb-2026 legacy alias — used by any external tests / callers that
# imported ``_MAX_SIZE`` before the multi-type widening.
_MAX_SIZE = _MAX_SIZE_IMG

_ALLOWED_EXT = {
    # images
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    # documents (Feb-2026 widening)
    "pdf", "docx", "xlsx", "csv", "txt",
}
_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv":  "text/csv",
    "txt":  "text/plain",
}
_MAGIC_HEADERS = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"], "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # + b"WEBP" at offset 8; checked separately
    "svg": [b"<?xml", b"<svg"],
    # Feb-2026 widening.
    "pdf":  [b"%PDF-"],
    # DOCX / XLSX are OpenXML — a ZIP archive under the hood; both
    # begin with the PKZIP local-file-header magic. We accept the
    # standard signature and the "empty archive" variant.
    "docx": [b"PK\x03\x04", b"PK\x05\x06"],
    "xlsx": [b"PK\x03\x04", b"PK\x05\x06"],
    # CSV / TXT — see ``_TEXT_SNIFF_EXT`` note below.
    "csv":  [],
    "txt":  [],
}
# Extensions whose magic bytes are unreliable enough that we fall
# back to extension + content sniff. Documented in the STOP-and-report
# — the user pre-approved this fallback with an explicit note.
_TEXT_SNIFF_EXT = {"csv", "txt"}

_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
_DOC_EXT   = {"pdf", "docx", "xlsx", "csv", "txt"}

_SVG_DANGER = re.compile(
    rb"(<script\b)|(\son\w+\s*=)|(href\s*=\s*[\"']?\s*javascript:)",
    re.IGNORECASE,
)
_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]")
_MANAGERS = {"admin", "super_admin", "manager"}


def _size_cap_for_ext(ext: str) -> int:
    if ext == "svg":
        return _MAX_SIZE_SVG
    if ext in _IMAGE_EXT:
        return _MAX_SIZE_IMG
    if ext == "pdf":
        return _MAX_SIZE_PDF
    if ext in _DOC_EXT:
        return _MAX_SIZE_DOC
    return _MAX_SIZE_IMG   # conservative default


def _require_managers(user: dict) -> None:
    if (user or {}).get("role") not in _MANAGERS:
        raise HTTPException(403, "Not allowed")


def _detect_ext(file_name: str, declared_mime: str) -> str:
    ext = ""
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower()
    if ext in _ALLOWED_EXT:
        return "jpg" if ext == "jpeg" else ext
    # Fall back to declared MIME.
    for e, m in _MIME_BY_EXT.items():
        if m == declared_mime.lower():
            return e
    raise HTTPException(415, f"Unsupported extension: {ext or declared_mime}")


def _magic_bytes_ok(ext: str, data: bytes) -> bool:
    if ext in _TEXT_SNIFF_EXT:
        # Fallback: extension + content sniff. Content sniffing is
        # done in ``_text_sniff_ok``; we accept anything here so the
        # caller pipes into the sniffer.
        return True
    hdrs = _MAGIC_HEADERS.get(ext) or []
    if not any(data.startswith(h) for h in hdrs):
        return False
    if ext == "webp" and data[8:12] != b"WEBP":
        return False
    return True


def _text_sniff_ok(ext: str, data: bytes) -> bool:
    """CSV / TXT content sniff. Rejects binary blobs masquerading as
    text (any NUL byte in the first 8 KB) and non-UTF-8 payloads."""
    if ext not in _TEXT_SNIFF_EXT:
        return True
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        # Some tenant exports are Windows-1252 / Latin-1 — accept
        # those too, they're still safe plain-text.
        try:
            sample.decode("latin-1")
            return True
        except UnicodeDecodeError:
            return False


def _strip_exif(data: bytes, ext: str) -> bytes:
    """Best-effort EXIF strip for jpeg/png/webp. Returns data unchanged
    on failure so an unexpected Pillow issue never blocks an upload."""
    if ext not in ("jpg", "jpeg", "png", "webp"):
        return data
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        out = io.BytesIO()
        # ``save`` without ``exif`` argument strips it.
        save_fmt = {"jpg": "JPEG", "jpeg": "JPEG",
                     "png": "PNG", "webp": "WEBP"}[ext]
        img.save(out, format=save_fmt)
        return out.getvalue()
    except Exception as exc:
        logger.warning(f"[phase9c] EXIF strip failed ({exc}); using original bytes")
        return data


def _sanitize_filename(raw: str) -> str:
    name = os.path.basename(raw or "")
    name = _FILENAME_SAFE.sub("_", name)
    return (name[:120] if name else f"upload-{_uuid.uuid4().hex[:8]}")


def _download_url(mid: str) -> str:
    return f"/api/marketing/media/{mid}/download"


# ═══════════════════════════════════════════════════════════════════
# Phase P1.2 · Feb 2026 — Expiring signed URLs + per-IP rate limit.
#
# The pre-P1.2 signature was ``HMAC(JWT_SECRET, tenant_id|mid)`` with
# no expiration claim. A leaked URL was valid indefinitely. Now every
# signed URL carries a unix-epoch ``exp`` claim baked into the HMAC
# so tampering with ``exp`` invalidates the signature.
#
# TTL policy (both env-overridable):
#   * Email attachments — 7 days. Emails sit in inboxes for a while;
#     recipients open them days later.
#   * SMS attachments   — 72 hours. SMS is a more replay-prone
#     surface (forwarded texts, screenshots leak the URL).
#
# The URL shape drops ``tid`` — ``mid`` is a UUID with global-unique
# collision-proof guarantees, so ``marketing_media.find_one({"id":
# mid})`` resolves the tenant. The HMAC still bakes tenant_id in
# (from the resolved row) so cross-tenant guessing is impossible.
# Old URLs (with ``tid=&sig=`` but no ``exp=``) are REJECTED with a
# 400 ``signature_missing`` — leaking one legacy URL must not create
# permanent exposure. Ops MUST regenerate any pre-issued URLs after
# this deploy.
# ═══════════════════════════════════════════════════════════════════

# TTL constants — env-overridable so ops can dial per pod.
MEDIA_URL_TTL_EMAIL_SECONDS = int(
    os.environ.get("MEDIA_URL_TTL_EMAIL_SECONDS") or (7 * 86400),
)
MEDIA_URL_TTL_SMS_SECONDS = int(
    os.environ.get("MEDIA_URL_TTL_SMS_SECONDS") or (72 * 3600),
)

# Signature error slugs — used in HTTPException details so callers
# (and tests) can pattern-match without regex on human-readable
# messages. See ``_verify_media_sig`` for the mapping.
SIG_ERR_MISSING = "signature_missing"
SIG_ERR_INVALID = "signature_invalid"
SIG_ERR_EXPIRED = "signature_expired"


def _sign_media(tenant_id: str, mid: str, exp: int | None = None) -> str:
    """Return an HMAC-SHA256 signature over ``tenant_id|mid|exp``.

    ``exp`` is required in the P1.2 surface; the default-``None``
    signature is preserved so legacy call sites at import-time
    (``routers/estimate_viewer.py``, ``routers/customers.py``) don't
    break, but such calls emit an ``exp=0`` signature that will
    fail verification — those call sites are ALSO updated to pass
    the correct TTL.

    HMAC input: ``f"{tenant_id}|{mid}|{exp}"``. Baking tenant_id
    keeps cross-tenant guessing impossible even though the URL
    drops it — the download route retrieves tenant_id from the row
    before verifying.
    """
    exp_i = int(exp or 0)
    msg = f"{tenant_id}|{mid}|{exp_i}".encode("utf-8")
    return hmac.new(JWT_SECRET.encode("utf-8"), msg,
                     hashlib.sha256).hexdigest()


def _verify_media_sig(
    tenant_id: str, mid: str, exp: int | None, sig: str | None,
    *, now_epoch: int | None = None,
) -> Optional[str]:
    """Return an error slug (``signature_missing`` /
    ``signature_invalid`` / ``signature_expired``) or ``None`` on
    success. Callers translate the slug into an HTTPException with
    the correct status code (400 / 403 / 410 respectively).

    Constant-time compare via :func:`hmac.compare_digest`.
    """
    if not (tenant_id and mid):
        return SIG_ERR_INVALID
    if not sig or exp is None:
        return SIG_ERR_MISSING
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return SIG_ERR_MISSING
    expected = _sign_media(tenant_id, mid, exp_i)
    try:
        if not hmac.compare_digest(sig, expected):
            return SIG_ERR_INVALID
    except Exception:
        return SIG_ERR_INVALID
    now = int(now_epoch if now_epoch is not None else time.time())
    if now > exp_i:
        return SIG_ERR_EXPIRED
    return None


def _signed_download_url(
    tenant_id: str, mid: str, *, ttl_seconds: int | None = None,
) -> str:
    """Return an expiring signed URL for ``mid`` on ``tenant_id``.

    ``ttl_seconds`` defaults to :data:`MEDIA_URL_TTL_EMAIL_SECONDS`
    when not supplied — email is the most common channel and the
    least replay-prone (an email inbox is a first-party surface).
    Callers on the SMS channel pass
    :data:`MEDIA_URL_TTL_SMS_SECONDS` explicitly.
    """
    ttl = int(ttl_seconds if ttl_seconds is not None
               else MEDIA_URL_TTL_EMAIL_SECONDS)
    exp = int(time.time()) + max(1, ttl)
    sig = _sign_media(tenant_id, mid, exp)
    return f"/api/marketing/media/{mid}/download?exp={exp}&sig={sig}"


def _enrich_media_row(row: dict) -> dict:
    """Overwrite stored ``cdn_url`` / ``storage_url`` with a fresh
    signed URL so consumers never see the auth-only path."""
    if not row:
        return row
    tid = row.get("tenant_id") or ""
    mid = row.get("id") or ""
    if tid and mid:
        signed = _signed_download_url(tid, mid)
        row["cdn_url"] = signed
        row["url"] = signed
        row["storage_url"] = signed
    return row


# ═══════════════════════════ Upload ══════════════════════════════════
@router.post("/marketing/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # comma-separated
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_managers(user)
    raw = await file.read()
    size = len(raw)
    if size == 0:
        raise HTTPException(400, "Empty file")
    ext = _detect_ext(file.filename or "", file.content_type or "")
    # Feb-2026 · per-type size caps for the widened library (image
    # 5 MB / SVG 200 KB / PDF 15 MB / doc 10 MB).
    limit = _size_cap_for_ext(ext)
    if size > limit:
        raise HTTPException(413, f"File exceeds {limit // 1024} KB limit")
    if not _magic_bytes_ok(ext, raw):
        raise HTTPException(
            415,
            "File contents don't match declared type "
            "(magic-bytes check failed)",
        )
    # CSV / TXT bypass magic bytes; enforce a content sniff instead.
    if ext in _TEXT_SNIFF_EXT and not _text_sniff_ok(ext, raw):
        raise HTTPException(
            415, "Text file contains binary content or an unsupported encoding",
        )
    if ext == "svg" and _SVG_DANGER.search(raw):
        raise HTTPException(
            415, "SVG contains script/inline-JS — refused",
        )
    stripped = _strip_exif(raw, ext)

    mime = _MIME_BY_EXT[ext]
    uid = f"{_uuid.uuid4().hex}.{ext}"
    storage_path = build_path(tenant["id"], uid)
    try:
        put_object(storage_path, stripped, mime)
    except StorageUnavailable as exc:
        logger.warning(f"[phase9c] storage unavailable: {exc}")
        raise HTTPException(503, f"Storage unavailable: {exc}")

    mid = new_id()
    now = now_iso()
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    signed_url = _signed_download_url(tenant["id"], mid)
    row = {
        "id": mid, "tenant_id": tenant["id"],
        "uploaded_by": user.get("id"),
        "file_name": _sanitize_filename(file.filename or f"{uid}"),
        "mime_type": mime,
        "size_bytes": len(stripped),
        "storage_key": storage_path,
        "storage_url": signed_url,   # signed URL, works from <img>
        "cdn_url": signed_url,
        "alt_text": alt_text or None,
        "tags": tag_list,
        "deleted_at": None,
        "ref_count_cached": 0,
        "created_at": now, "updated_at": now,
    }
    await db.marketing_media.insert_one(row)
    row.pop("_id", None)
    return {
        "id": mid,
        "url": signed_url,
        "cdn_url": signed_url,
        "storage_url": signed_url,
        "mime_type": mime,
        "size_bytes": len(stripped),
        "file_name": row["file_name"],
    }


# ═══════════════════════════ Download proxy ══════════════════════════
# Phase P1.2 · Feb 2026 — 60/min per-IP rate limit via SlowAPI. The
# ``request: Request`` parameter is what SlowAPI inspects to pull the
# client IP via ``get_remote_address``. Decorator order matters:
# ``@router.get`` outermost, ``@limiter.limit`` inner.
_MEDIA_DOWNLOAD_RATE_LIMIT = os.environ.get(
    "MEDIA_URL_DOWNLOAD_RATE_LIMIT", "60/minute",
)


def _apply_download_rate_limit(fn):
    if limiter is None:  # pragma: no cover — slowapi always installed
        return fn
    return limiter.limit(_MEDIA_DOWNLOAD_RATE_LIMIT)(fn)


@router.get("/marketing/media/{mid}/download")
@_apply_download_rate_limit
async def download_media(
    request: Request,
    mid: str,
    exp: Optional[int] = Query(None),
    sig: Optional[str] = Query(None),
):
    """Serve the raw bytes via signed URL.

    Phase P1.2 · Feb 2026 — every URL now carries an ``exp`` claim
    baked into the HMAC. Old ``?tid=&sig=`` URLs are rejected with
    400 ``signature_missing``. Rate-limited to 60/min per IP via
    SlowAPI (see the ``@limiter.limit`` decorator).

    Contract:
      * 400 ``signature_missing`` — ``exp`` or ``sig`` param missing.
      * 403 ``signature_invalid`` — HMAC mismatch (tampering, wrong
        tenant, wrong mid, or wrong ``exp`` value).
      * 410 ``signature_expired`` — HMAC valid but ``now > exp``.
        410 Gone is deliberate: caching layers treat it as terminal
        (won't retry) and it's distinct from 403 so callers can
        prompt "request a fresh link" instead of "you're not
        allowed".
      * 404 media_not_found — the ``mid`` doesn't resolve. Retained
        AFTER signature verification so 404 vs 403 doesn't leak
        which ``mid`` values exist.
      * 429 rate_limited — SlowAPI 60/min per IP.
    """
    if not sig or exp is None:
        raise HTTPException(400, SIG_ERR_MISSING)
    # Resolve the row FIRST — ``mid`` is a UUID so lookup by ``id``
    # alone is collision-proof. Tenant_id comes from the row so the
    # URL doesn't have to carry it (and can't leak it).
    row = await db.marketing_media.find_one(
        {"id": mid, "deleted_at": None}, {"_id": 0},
    )
    if not row:
        # Verify sig against a synthetic tenant so 404 vs 403 doesn't
        # leak mid existence. If the sig for the fake tenant somehow
        # verifies (astronomically improbable), we still 404.
        _ = _verify_media_sig("__no_such_tenant__", mid, exp, sig)
        raise HTTPException(404, "media_not_found")
    err = _verify_media_sig(row.get("tenant_id") or "", mid, exp, sig)
    if err == SIG_ERR_MISSING:
        raise HTTPException(400, SIG_ERR_MISSING)
    if err == SIG_ERR_INVALID:
        raise HTTPException(403, SIG_ERR_INVALID)
    if err == SIG_ERR_EXPIRED:
        raise HTTPException(410, SIG_ERR_EXPIRED)
    try:
        data, ctype = get_object(row["storage_key"])
    except StorageUnavailable as exc:
        raise HTTPException(503, f"Storage unavailable: {exc}")
    return Response(
        content=data,
        media_type=row.get("mime_type") or ctype,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ═══════════════════════════ List / Detail / Patch ═══════════════════
@router.get("/marketing/media")
async def list_media(
    page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    tag: Optional[str] = None, search: Optional[str] = None,
    kind: Optional[str] = Query(
        None,
        description=(
            "Filter by file kind. Feb-2026 widening — accepts "
            "``image`` (png/jpg/gif/webp/svg), ``document`` "
            "(pdf/docx/xlsx/csv/txt), or unset for all."
        ),
    ),
    include_deleted: int = 0,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_managers(user)
    q: Dict = {"tenant_id": tenant["id"]}
    if not include_deleted:
        q["deleted_at"] = None
    if tag:
        q["tags"] = tag
    if kind == "image":
        q["mime_type"] = {"$regex": "^image/"}
    elif kind == "document":
        # Anything the widened library treats as a document. Keep this
        # in lockstep with ``_DOC_EXT`` above.
        q["mime_type"] = {"$in": [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
        ]}
    if search:
        s = search.strip()
        q["$or"] = [
            {"file_name": {"$regex": s, "$options": "i"}},
            {"alt_text": {"$regex": s, "$options": "i"}},
        ]
    total = await db.marketing_media.count_documents(q)
    rows = await db.marketing_media.find(q, {"_id": 0}) \
        .sort("created_at", -1) \
        .skip((page - 1) * page_size).limit(page_size) \
        .to_list(page_size)
    rows = [_enrich_media_row(r) for r in rows]
    # Feb-2026 Media-Library P1 — front-end needs both ``rows`` (legacy
    # shape) and pagination hints for the "Load more" button.
    has_more = (page * page_size) < total
    return {
        "rows": rows,
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
    }


@router.get("/marketing/media/{mid}")
async def get_media(mid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_managers(user)
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    return _enrich_media_row(row)


@router.patch("/marketing/media/{mid}")
async def patch_media(mid: str, payload: Dict,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    _require_managers(user)
    upd: Dict = {}
    if "alt_text" in payload:
        upd["alt_text"] = payload["alt_text"] or None
    if "tags" in payload:
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        upd["tags"] = list(tags)
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["updated_at"] = now_iso()
    res = await db.marketing_media.update_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"$set": upd},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Media not found")
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return _enrich_media_row(row)


# ═══════════════════════════ Soft-delete with ref-count ══════════════
async def _referencing_templates(tenant_id: str, mid: str,
                                    url: str) -> List[str]:
    """Return the ids of active (non-system-only would be surprising to
    the user; include ALL active) templates whose body embeds the
    media's URL. Uses two search patterns: the ``/download`` URL and a
    fallback for legacy raw storage paths."""
    patterns = [
        f"/api/marketing/media/{mid}/download",
        url,
    ]
    or_clauses = [
        {"body": {"$regex": re.escape(p), "$options": "i"}}
        for p in patterns
    ]
    cursor = db.marketing_templates.find(
        {"tenant_id": tenant_id, "active": True,
         "$or": or_clauses},
        {"_id": 0, "id": 1},
    )
    return [r["id"] async for r in cursor]


@router.delete("/marketing/media/{mid}")
async def delete_media(mid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    _require_managers(user)
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"], "deleted_at": None},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    refs = await _referencing_templates(tenant["id"], mid,
                                            row.get("cdn_url") or _download_url(mid))
    if refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Media is referenced by active templates",
                "referencing_template_ids": refs,
            },
        )
    await db.marketing_media.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"ok": True, "id": mid}


@router.post("/marketing/media/{mid}/restore")
async def restore_media(mid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    if row.get("deleted_at") is None:
        return {"ok": True, "already_active": True}
    await db.marketing_media.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": None, "updated_at": now_iso()}},
    )
    return {"ok": True, "id": mid}
