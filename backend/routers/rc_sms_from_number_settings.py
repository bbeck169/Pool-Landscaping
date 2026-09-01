"""Phase G2 · Feb-2026 (TD-G1-1) — RC SMS from-number tenant setting.

Endpoints
---------
GET /api/admin/settings/rc-sms-from-number   — read (super_admin only)
PUT /api/admin/settings/rc-sms-from-number   — write (super_admin only)

Reads/writes the top-level ``tenants.rc_sms_from_number`` field
consumed by ``services.sms.rc_adapter._resolve_from`` and
``services.comms_hardening.deny_list``. When set (E.164 string), the
RC adapter uses this number as the SMS ``from`` for the tenant; when
null/unset, it falls back to env ``RC_SMS_DEFAULT_FROM``.

G2 ships the plumbing only. No UI in this phase — admins can set /
inspect via cURL until the settings tile lands.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from config import db, logger  # noqa: F401
from utils import require_super_admin

router = APIRouter()


_E164_RE = re.compile(r"^\+\d{10,15}$")


class RcSmsFromNumberPatch(BaseModel):
    # ``None`` clears the override (fall back to env). Explicit ``""`` is
    # rejected — set to null instead.
    rc_sms_from_number: Optional[str] = Field(
        default=None,
        description="E.164 phone number, or null to clear the override.",
    )

    @field_validator("rc_sms_from_number")
    @classmethod
    def _validate_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError(
                "empty string not allowed — send null to clear the override",
            )
        if not _E164_RE.match(v):
            raise ValueError(
                "must be an E.164 phone number (e.g. +16028874400)",
            )
        return v


@router.get("/admin/settings/rc-sms-from-number")
async def get_rc_sms_from_number(
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "user has no tenant_id")
    t = await db.tenants.find_one(
        {"id": tid}, {"_id": 0, "rc_sms_from_number": 1, "name": 1},
    ) or {}
    return {
        "tenant_id": tid,
        "tenant_name": t.get("name"),
        "rc_sms_from_number": t.get("rc_sms_from_number"),
        "env_fallback_note": (
            "When null, RC adapter falls back to env RC_SMS_DEFAULT_FROM."
        ),
    }


@router.put("/admin/settings/rc-sms-from-number")
async def put_rc_sms_from_number(
    body: RcSmsFromNumberPatch = Body(...),
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "user has no tenant_id")
    new_value = body.rc_sms_from_number  # may be None to clear
    await db.tenants.update_one(
        {"id": tid}, {"$set": {"rc_sms_from_number": new_value}},
    )
    logger.info(
        "[phase-g2] rc_sms_from_number %s for tenant=%s",
        "cleared" if new_value is None else f"set to {new_value}",
        tid,
    )
    return {
        "tenant_id": tid,
        "rc_sms_from_number": new_value,
        "updated": True,
    }
