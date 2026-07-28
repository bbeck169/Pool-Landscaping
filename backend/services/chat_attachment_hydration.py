"""Phase B2 · Feb 2026 — Shared attachment-hydration for chat messages.

Used by both PortalChatsPage (customer + admin) and TeamChatPage
(staff) so both call-sites read F0 attachments through a single code
path. Reads ``attachment_ids: List[str]`` on each message and returns
the same list of message dicts with an ``attachments`` field appended:

    attachments = [
        {
            "id": "<file_id>",
            "filename": "<original_filename>",
            "mime": "<content_type>",
            "size": <bytes>,
            "signed_url": "/api/files/<id>/download",
        },
        ...
    ]

Tenant scope is enforced — only files whose ``tenant_id`` matches the
caller's tenant are surfaced (defense-in-depth). Missing / deleted /
cross-tenant ids are silently dropped from the output.

Note: the ``signed_url`` returned is a bearer-guarded URL, not a true
short-lived signed URL. Clients render it via ``<AuthedImage>`` or an
``?auth=<token>`` query variant. Naming it ``signed_url`` matches the
external API contract the frontend expects.
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import db


def _to_tile(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc.get("id"),
        "filename": doc.get("original_filename") or "file",
        "mime": doc.get("content_type") or "application/octet-stream",
        "size": int(doc.get("size") or 0),
        "signed_url": f"/api/files/{doc.get('id')}/download",
    }


async def hydrate_message_attachments(
    messages: List[Dict[str, Any]], tenant_id: str,
) -> List[Dict[str, Any]]:
    """In-place attach ``attachments`` list onto each message dict.
    Returns the same list. Safe on messages that have no ``attachment_ids``."""
    if not messages:
        return messages
    all_ids: set = set()
    for m in messages:
        for aid in (m.get("attachment_ids") or []):
            if aid:
                all_ids.add(aid)
    if not all_ids:
        for m in messages:
            m.setdefault("attachments", [])
        return messages
    rows = await db.files.find(
        {"id": {"$in": list(all_ids)}, "tenant_id": tenant_id,
         "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).to_list(len(all_ids) * 2)
    by_id = {r.get("id"): _to_tile(r) for r in rows if r.get("id")}
    for m in messages:
        m["attachments"] = [
            by_id[aid] for aid in (m.get("attachment_ids") or [])
            if aid in by_id
        ]
    return messages
