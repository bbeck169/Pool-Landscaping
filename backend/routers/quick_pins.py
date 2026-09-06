"""Phase K75 · Step B · Feb-2026 — user quick-pin CRUD.

Endpoints:

* ``GET  /api/users/me/quick-pins`` — return the authenticated
  user's saved pin list. Returns ``{"pins": []}`` when unset — the
  frontend rail seeds its defaults CLIENT-SIDE for first-run so a
  brand-new user doesn't materialise a defaulted record until they
  explicitly customise. Preserves the "GET is read-only" invariant.

* ``PUT  /api/users/me/quick-pins`` — replace the full pin array.
  Server-side validation:
    1. ``len(pins) <= 15``            → 400 ``pin_cap_exceeded``.
    2. Duplicate ``to`` values        → 400 ``duplicate_pin``.
    3. Each ``to`` matches the caller's role registry
       (starts with ``/``, no ``..``, ≤ 200 chars, and — for
       tech / customer — must live inside the role's route
       allow-list; admins can pin any path since they navigate
       the whole IA).                → 400 ``foreign_route`` or
       ``wrong_role_route``.
    4. ``iconKey`` in ``ICON_WHITELIST``.  → 400 ``icon_not_whitelisted``.
    5. ``label`` non-empty after strip, ≤ 40 chars.
                                       → 400 ``label_invalid``.
  All writes are scoped to the caller's own user document — never
  by ``uid`` — so cross-user isolation is enforced by design.

Storage: ``users.preferences.quickPins`` — an array of
``{to, label, iconKey}`` objects on the ``users`` doc. The
``preferences`` sub-doc is created on first PUT (``$set`` is
Mongo-safe for missing nested paths).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso

router = APIRouter(tags=["K75 · User quick-pins"])


# ─── Whitelists ──────────────────────────────────────────────────────
# Mirror of ``frontend/src/nav/lucideIcons.js::ICON_WHITELIST``.
# The K75 pytest contract test regexes both files so the lists can't
# drift silently.
ICON_WHITELIST: frozenset[str] = frozenset({
    "layout_dashboard", "wrench", "calendar_days", "receipt", "credit_card",
    "users", "user_plus", "file_text", "waves", "clock", "timer",
    "bar_chart_3", "settings", "door_open", "layout_grid", "graduation_cap",
    "user_circle", "home", "shopping_cart", "truck", "star", "bell",
    "message_square", "mail", "map", "clipboard_list", "package", "tag",
    "sparkles", "bot", "book_open", "shield_check", "building_2", "camera",
    "external_link",
})

# Cap enforced by the K75 spec.
QUICK_PINS_CAP: int = 15


# Per-role route registries — mirror of
# ``frontend/src/nav/topNavRegistry.js`` + ``defaultQuickPins.js``
# **plus** every ``ADMIN_NAV_V2`` entry (which lives in the JS side
# only). Admin/manager/super_admin get a permissive gate — any path
# is fine as long as it looks like a route (starts with ``/``, no
# path-traversal, ≤ 200 chars) — because they navigate the whole
# ~130-page IA. Techs + customers get an explicit prefix allow-list.
_TECH_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/",              # tech home (dashboard)
    "/schedule",
    "/d2d",
    "/tech/",
    "/tests",
    "/portal/profile",
    "/portal/tos",
    "/landscape/time-clock",
    "/job-timers",
    "/customers",     # tech reads customer pages read-only
    "/estimates",
    "/invoices",
)
_CUSTOMER_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/portal/",
    "/customer/",
)


def _looks_like_route(to: str) -> bool:
    """Cheap syntactic gate applied to every role. Refuses:
       • empty strings and non-string paths
       • paths that don't start with ``/``
       • path-traversal (``..``)
       • absurdly long strings (Mongo doc bloat guard)
       • URL protocols (``http://…``) — pins are IN-APP only
    """
    if not to or not isinstance(to, str):
        return False
    if not to.startswith("/"):
        return False
    if ".." in to:
        return False
    if len(to) > 200:
        return False
    # No embedded schemes.
    if re.search(r"^https?:|^javascript:|^data:", to, re.I):
        return False
    return True


def _tech_route_ok(to: str) -> bool:
    # ``/`` is the tech home dashboard — allowed but as an exact
    # match (not a prefix, or every path would match).
    if to == "/":
        return True
    return any(
        # Skip the "/" prefix so it doesn't match every path.
        to == p or to.startswith(p if p.endswith("/") else p + "/") or to.startswith(p + "?")
        for p in _TECH_ALLOWED_PREFIXES if p != "/"
    ) or any(
        to == p for p in _TECH_ALLOWED_PREFIXES
    )


def _customer_route_ok(to: str) -> bool:
    return any(
        to == p or to.startswith(p) for p in _CUSTOMER_ALLOWED_PREFIXES
    )


def _route_ok_for_role(to: str, role: Optional[str]) -> bool:
    if not _looks_like_route(to):
        return False
    if role in ("admin", "super_admin", "manager"):
        return True  # permissive — admins reach the whole IA
    if role == "technician":
        return _tech_route_ok(to)
    if role in ("customer", "customer_portal"):
        return _customer_route_ok(to)
    # Unknown roles never pin.
    return False


# ─── Pydantic ────────────────────────────────────────────────────────
class QuickPin(BaseModel):
    to: str = Field(..., description="In-app route, e.g. ``/schedule``.")
    label: str = Field(..., description="Display label (≤ 40 chars).")
    iconKey: str = Field(..., description="Whitelisted lucide-react key.")


class QuickPinsPutBody(BaseModel):
    pins: List[QuickPin]


# ─── Endpoints ───────────────────────────────────────────────────────
@router.get("/users/me/quick-pins",
             operation_id="users.getQuickPins")
async def get_quick_pins(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the caller's saved pin list. ``[]`` for first-run
    (the frontend rail seeds defaults client-side — see the
    module docstring for rationale)."""
    prefs = (user.get("preferences") or {}) if isinstance(user, dict) else {}
    pins_raw = prefs.get("quickPins")
    if not isinstance(pins_raw, list):
        return {"pins": []}
    # Defensive filter — a legacy row might have stored a malformed
    # pin. We only surface pins that still validate against the
    # current whitelist so the UI never crashes on a stale iconKey.
    role = user.get("role")
    clean: List[Dict[str, Any]] = []
    for p in pins_raw:
        if not isinstance(p, dict):
            continue
        to = p.get("to")
        icon = p.get("iconKey")
        label = p.get("label")
        if not isinstance(to, str) or not isinstance(icon, str) or not isinstance(label, str):
            continue
        if icon not in ICON_WHITELIST:
            continue
        if not _route_ok_for_role(to, role):
            continue
        clean.append({"to": to, "label": label, "iconKey": icon})
    return {"pins": clean}


@router.put("/users/me/quick-pins",
             operation_id="users.putQuickPins")
async def put_quick_pins(
    body: QuickPinsPutBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Replace the caller's full pin list. See module docstring
    for the validation matrix."""
    role = user.get("role")
    pins = body.pins

    # Cap.
    if len(pins) > QUICK_PINS_CAP:
        raise HTTPException(
            400, detail={"code": "pin_cap_exceeded", "cap": QUICK_PINS_CAP,
                          "received": len(pins)},
        )

    seen: set[str] = set()
    normalized: List[Dict[str, Any]] = []
    for p in pins:
        to = (p.to or "").strip()
        label = (p.label or "").strip()
        icon = (p.iconKey or "").strip()

        # Label.
        if not label:
            raise HTTPException(
                400, detail={"code": "label_invalid", "reason": "empty",
                              "pin_to": to},
            )
        if len(label) > 40:
            raise HTTPException(
                400, detail={"code": "label_invalid",
                              "reason": "over_max_length",
                              "max_len": 40, "pin_to": to},
            )

        # Icon whitelist.
        if icon not in ICON_WHITELIST:
            raise HTTPException(
                400, detail={"code": "icon_not_whitelisted",
                              "pin_to": to, "iconKey": icon},
            )

        # Route syntactic gate.
        if not _looks_like_route(to):
            raise HTTPException(
                400, detail={"code": "foreign_route", "pin_to": to},
            )

        # Role registry gate.
        if not _route_ok_for_role(to, role):
            raise HTTPException(
                400, detail={"code": "wrong_role_route",
                              "pin_to": to, "role": role},
            )

        # Duplicate check.
        if to in seen:
            raise HTTPException(
                400, detail={"code": "duplicate_pin", "pin_to": to},
            )
        seen.add(to)
        normalized.append({"to": to, "label": label, "iconKey": icon})

    # Write scoped to the caller — never accept a ``uid`` arg.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"preferences.quickPins": normalized,
                   "preferences.quickPins_updated_at": now_iso(),
                   "updated_at": now_iso()}},
    )
    logger.info("[k75-quick-pins] user=%s wrote %s pin(s)",
                 user.get("id"), len(normalized))
    return {"ok": True, "pins": normalized}
