"""Feb-2026 · Customer-Attachments (Option D).

Helpers used by ``routers/customers.py`` and any other caller that
needs to turn a list of ``marketing_media`` file IDs into a real
attachment payload (base64 for email) or a public URL list (for SMS).

Contract:
    * Everything is tenant-scoped. A file whose row lives in a
      different tenant is treated as "not found" — we raise
      ``FileNotFoundError`` with the offending id so the router
      can 404 with ``{"code":"file_not_found","file_id":…}``.
    * Storage failures raise ``StorageUnavailable`` and are
      converted to 502 by the caller.
    * Never returns partial results — if any file in the batch
      fails, the whole batch aborts (matches the spec: "do NOT
      send a half-attached email / half of the URLs").
"""
from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional, Tuple

from services.marketing_media.storage_client import (
    StorageUnavailable, get_object,
)
from services.tenants.business_settings import resolve_absolute_url


def _db():
    """Late-bound Motor DB accessor.

    Feb-2026 test-infra note — importing ``config.db`` at module load
    binds the reference to whichever event loop was live at import.
    Test infra rotates the loop via ``_f7_loop_fixture.run_test``,
    which iterates a known list of modules to rebind. Rather than
    force every new helper module onto that list, resolve ``db`` at
    call-time so we always see the current binding.
    """
    from config import db
    return db


# ─── Size caps (email-attachment side) ────────────────────────────
PER_FILE_MAX_BYTES  = 10 * 1024 * 1024        # 10 MB per file
TOTAL_MAX_BASE64_BYTES = 20 * 1024 * 1024     # 20 MB total base64 payload


class MediaFileNotFound(Exception):
    """A file_id isn't in this tenant's ``marketing_media`` (missing
    or belongs to a different tenant)."""

    def __init__(self, file_id: str) -> None:
        super().__init__(f"file_not_found: {file_id}")
        self.file_id = file_id


class AttachmentTooLarge(Exception):
    """Per-file or cumulative cap exceeded. ``code`` distinguishes
    which cap fired so the router can surface a targeted 413."""

    def __init__(self, code: str, *, file_id: Optional[str] = None,
                    size_bytes: Optional[int] = None,
                    limit_bytes: Optional[int] = None) -> None:
        super().__init__(f"{code}: file={file_id} size={size_bytes} limit={limit_bytes}")
        self.code = code
        self.file_id = file_id
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


async def _fetch_row(tenant_id: str, file_id: str) -> Dict[str, Any]:
    row = await _db().marketing_media.find_one(
        {"id": file_id, "tenant_id": tenant_id, "deleted_at": None},
        {"_id": 0},
    )
    if not row:
        raise MediaFileNotFound(file_id)
    return row


async def resolve_email_attachments(
    tenant_id: str, file_ids: List[str],
) -> List[Dict[str, Any]]:
    """Return a list of Resend-shaped attachment dicts:
        ``{filename, content_type, content_base64}``

    Enforces per-file (10 MB raw) and cumulative (20 MB base64) caps.
    Raises :class:`MediaFileNotFound` or :class:`AttachmentTooLarge`
    on failure — the caller (customers router) maps to 404 / 413.
    """
    out: List[Dict[str, Any]] = []
    total_b64_bytes = 0
    for fid in file_ids:
        row = await _fetch_row(tenant_id, fid)
        # Per-file raw-byte cap (before base64 blow-up).
        raw_size = int(row.get("size_bytes") or 0)
        if raw_size > PER_FILE_MAX_BYTES:
            raise AttachmentTooLarge(
                "file_too_large",
                file_id=fid,
                size_bytes=raw_size,
                limit_bytes=PER_FILE_MAX_BYTES,
            )
        data, ctype = get_object(row["storage_key"])
        # Recompute in case the stored size_bytes drifted from reality.
        if len(data) > PER_FILE_MAX_BYTES:
            raise AttachmentTooLarge(
                "file_too_large",
                file_id=fid,
                size_bytes=len(data),
                limit_bytes=PER_FILE_MAX_BYTES,
            )
        b64 = base64.b64encode(data).decode("ascii")
        total_b64_bytes += len(b64)
        if total_b64_bytes > TOTAL_MAX_BASE64_BYTES:
            raise AttachmentTooLarge(
                "attachments_too_large_total",
                file_id=fid,
                size_bytes=total_b64_bytes,
                limit_bytes=TOTAL_MAX_BASE64_BYTES,
            )
        out.append({
            "filename":       row.get("file_name") or f"{fid}",
            "content_type":   row.get("mime_type") or ctype
                                or "application/octet-stream",
            "content_base64": b64,
        })
    return out


async def resolve_sms_public_urls(
    tenant_id: str, file_ids: List[str], *,
    sign_media: callable = None,
    build_signed_url: callable = None,
    ttl_seconds: int | None = None,
) -> List[Tuple[str, str]]:
    """For each file_id, return ``(file_name, absolute_signed_url)``.

    Phase P1.2 · Feb 2026 — signed URLs now embed an ``exp`` claim,
    so this helper needs the URL BUILDER (``build_signed_url``) rather
    than a raw sign function. ``sign_media`` is retained for
    backwards-compat with any legacy caller that still passes it —
    a legacy call is a NO-OP that yields the same empty output as
    calling with an empty file_ids list, so a mistaken caller can't
    accidentally emit unexpiring URLs.

    Caller pattern (new)::

        from routers.marketing_media import (
            _signed_download_url, MEDIA_URL_TTL_SMS_SECONDS,
        )
        urls = await resolve_sms_public_urls(
            tid, ids,
            build_signed_url=_signed_download_url,
            ttl_seconds=MEDIA_URL_TTL_SMS_SECONDS,
        )
    """
    if build_signed_url is None:
        # Legacy call path — refuse to emit URLs. A caller stuck on
        # the pre-P1.2 shape gets an empty list instead of a
        # never-expiring URL leak.
        return []
    out: List[Tuple[str, str]] = []
    for fid in file_ids:
        row = await _fetch_row(tenant_id, fid)
        relative = build_signed_url(
            tenant_id, fid, ttl_seconds=ttl_seconds,
        )
        absolute = resolve_absolute_url(relative) or relative
        out.append((row.get("file_name") or fid, absolute))
    return out


def format_sms_attachments_suffix(urls: List[Tuple[str, str]]) -> str:
    """Render the SMS body suffix. Plain, no emoji, no fancy prefixes
    — per the user's answer to the STOP-and-report side question."""
    if not urls:
        return ""
    lines = "\n".join(u for _fn, u in urls)
    return f"\n\nAttachments:\n{lines}"
