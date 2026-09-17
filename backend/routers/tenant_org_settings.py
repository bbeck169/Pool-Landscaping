"""Feb-2026 · Ticket #3 + #4 · Organization-level Settings API.

Two new tabs in the SettingsHub sidebar:
  * **Notifications** — 4 org-wide send-path toggles (each defaults ``True``).
  * **AI Configuration** — persona name + KB uploads on/off + analytics on/off.

Both live under ``tenants.settings.*`` to align with the shape used by
the existing ``settings.payment.*`` and ``settings.notifications.
auto_send_completion`` fields.

Endpoints
---------
* ``GET   /api/tenants/mine/settings/notifications`` — read (admin only)
* ``PATCH /api/tenants/mine/settings/notifications`` — partial update
* ``GET   /api/tenants/mine/settings/ai``            — read (admin only)
* ``PATCH /api/tenants/mine/settings/ai``            — partial update

The four notification toggles gate the ACTUAL send paths — see
``services/org_settings/notifications_gate.py::is_org_notification_
enabled`` for the shared read helper. KB uploads gate the
``POST /api/ai/knowledge/file`` handler. Analytics gate the
``services.ai.usage.record_usage`` call in the AI dispatcher.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from utils import require_admin


router = APIRouter(prefix="/tenants/mine", tags=["org-settings"])
log = logging.getLogger("tenant_org_settings")


NOTIFICATION_KEYS = (
    "lead_confirmation",
    "tech_on_my_way",
    "job_completion_summary",
    "warranty_expiration",
)

DEFAULT_NOTIFICATIONS: Dict[str, bool] = {k: True for k in NOTIFICATION_KEYS}

# AI defaults. ``persona_name`` falls back at read time to the tenant
# business name (or "AI Assistant") — the raw value stays ``None``
# in the doc until the admin explicitly sets it.
DEFAULT_AI: Dict[str, Any] = {
    "persona_name": None,
    "kb_uploads_enabled": True,
    "analytics_enabled": True,
}

PERSONA_NAME_MAX = 60


# ── Notification schemas ─────────────────────────────────────────
class NotificationSettingsIn(BaseModel):
    """Partial PATCH — every field optional so admins can flip one
    toggle at a time without echoing the whole block."""
    model_config = ConfigDict(extra="forbid")
    lead_confirmation: Optional[bool] = None
    tech_on_my_way: Optional[bool] = None
    job_completion_summary: Optional[bool] = None
    warranty_expiration: Optional[bool] = None


def _read_notifications(tenant: Dict[str, Any]) -> Dict[str, bool]:
    """Merge stored toggles with defaults. Missing keys default True."""
    settings = (tenant.get("settings") or {}).get("notifications") or {}
    out: Dict[str, bool] = {}
    for k in NOTIFICATION_KEYS:
        v = settings.get(k)
        out[k] = bool(v) if isinstance(v, bool) else True
    return out


@router.get("/settings/notifications")
async def get_notification_settings(
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    return _read_notifications(tenant)


@router.patch("/settings/notifications")
async def patch_notification_settings(
    body: NotificationSettingsIn,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    updates: Dict[str, Any] = {}
    for k in NOTIFICATION_KEYS:
        v = getattr(body, k)
        if v is not None:
            updates[f"settings.notifications.{k}"] = bool(v)
    if not updates:
        return _read_notifications(tenant)
    await db.tenants.update_one(
        {"id": tenant["id"]}, {"$set": updates},
    )
    fresh = await db.tenants.find_one({"id": tenant["id"]}) or tenant
    return _read_notifications(fresh)


# ── AI schemas ───────────────────────────────────────────────────
class AISettingsIn(BaseModel):
    """Partial PATCH for AI configuration."""
    model_config = ConfigDict(extra="forbid")
    persona_name: Optional[str] = Field(None, max_length=PERSONA_NAME_MAX)
    kb_uploads_enabled: Optional[bool] = None
    analytics_enabled: Optional[bool] = None


def _resolve_persona_fallback(tenant: Dict[str, Any]) -> str:
    """Best display name when the admin hasn't set ``persona_name``.
    Falls through: tenant business name → tenant name → "AI Assistant".
    """
    for k in ("business_name", "name"):
        v = tenant.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:PERSONA_NAME_MAX]
    return "AI Assistant"


def _read_ai(tenant: Dict[str, Any]) -> Dict[str, Any]:
    settings = (tenant.get("settings") or {}).get("ai") or {}
    persona = settings.get("persona_name")
    if not isinstance(persona, str) or not persona.strip():
        persona = _resolve_persona_fallback(tenant)
    return {
        "persona_name": persona,
        # ``None`` (unset) → True default.
        "kb_uploads_enabled": bool(settings.get("kb_uploads_enabled", True))
            if settings.get("kb_uploads_enabled") is not None else True,
        "analytics_enabled": bool(settings.get("analytics_enabled", True))
            if settings.get("analytics_enabled") is not None else True,
    }


@router.get("/settings/ai")
async def get_ai_settings(
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    return _read_ai(tenant)


@router.patch("/settings/ai")
async def patch_ai_settings(
    body: AISettingsIn,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    updates: Dict[str, Any] = {}
    if body.persona_name is not None:
        # Empty string clears back to fallback semantics — store ``None``.
        pn = body.persona_name.strip()
        updates["settings.ai.persona_name"] = pn or None
    if body.kb_uploads_enabled is not None:
        updates["settings.ai.kb_uploads_enabled"] = bool(body.kb_uploads_enabled)
    if body.analytics_enabled is not None:
        updates["settings.ai.analytics_enabled"] = bool(body.analytics_enabled)
    if not updates:
        return _read_ai(tenant)
    await db.tenants.update_one(
        {"id": tenant["id"]}, {"$set": updates},
    )
    fresh = await db.tenants.find_one({"id": tenant["id"]}) or tenant
    return _read_ai(fresh)
