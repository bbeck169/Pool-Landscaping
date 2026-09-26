"""MA1 · MARCO backend — ``POST /marco/execute``.

Contract
────────
Auth:  ``require_tech_or_above`` (admin / super_admin / technician).
Body:  ``MarcoExecuteBody``
    {"transcript": str, "screen": "job_detail"|"service_report",
     "entity_id": Optional[str]}
Response (200):
    {"action": str, "ok": bool, "code": Optional[str],
     "message": str, "meta": dict, "raw_llm": str}

Design
──────
Thin adapter. Delegates to :mod:`services.marco.parser` for LLM parse
and :mod:`services.marco.actions` for handler dispatch. Never raises
5xx for business errors — they surface as ``{ok: False, code: ...}``
so the client renders a friendly toast without special-casing HTTP
status codes.

Rulings applied — see the docstring on
:mod:`services.marco.actions` for the full list.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from routers.pool_calculators import require_tech_or_above
from routers.tenants import get_current_tenant
from services.marco.actions import ACTION_REGISTRY
from services.marco.parser import parse_transcript


router = APIRouter()


class MarcoExecuteBody(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=2000)
    screen: str = Field(..., pattern="^(job_detail|service_report)$")
    entity_id: Optional[str] = Field(default=None, max_length=64)


@router.post("/marco/execute")
async def execute(
    body: MarcoExecuteBody = Body(...),
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    parsed = await parse_transcript(
        transcript=body.transcript,
        tenant_id=tenant["id"],
    )
    # ── parser error surface ─────────────────────────────────────
    if parsed.get("error"):
        return {
            "action": None,
            "ok": False,
            "code": parsed["error"],
            "message": "Couldn't parse that command.",
            "meta": {"detail": parsed.get("detail", "")},
            "raw_llm": parsed.get("raw_llm", ""),
        }
    action = parsed["action"]
    if action == "unknown":
        return {
            "action": "unknown",
            "ok": False,
            "code": "unknown_action",
            "message": "I didn't understand that command.",
            "meta": {},
            "raw_llm": parsed.get("raw_llm", ""),
        }
    handler = ACTION_REGISTRY.get(action)
    if handler is None:
        # KNOWN_ACTIONS ⊆ ACTION_REGISTRY keys — this branch is a
        # defence-in-depth guard against future drift between the
        # parser's whitelist and this registry.
        return {
            "action": action,
            "ok": False,
            "code": "action_not_supported",
            "message": f"Action {action!r} is not supported.",
            "meta": {},
            "raw_llm": parsed.get("raw_llm", ""),
        }
    result = await handler(
        user=user, tenant=tenant,
        screen=body.screen,
        entity_id=body.entity_id or "",
        args=parsed.get("args") or {},
    )
    result.setdefault("action", action)
    result.setdefault("raw_llm", parsed.get("raw_llm", ""))
    return result
