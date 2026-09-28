"""MTH-A · Feb-2026 — Rule resolution: tenant overrides + platform
defaults → resolved rules + override_map.

Resolution semantics (per brief):
  1. Load the tenant's ``tenant_ai_rules`` doc (lazy-init if
     missing).
  2. Load the platform's ``platform_ai_rule_defaults`` doc.
  3. For every rule category:
     * If the tenant has an explicit override for a specific
       *sub-field* → use tenant.
     * Else → fall back to the platform default for that sub-field.
  4. Return ``ResolvedRules`` (a plain dict) alongside an
     ``override_map`` keyed by ``category.sub_field`` → ``"tenant"``
     or ``"platform"`` so the FE diff view can render provenance.

Cache: the resolved payload is memoised for 30 seconds
(``cache.TTL_SECONDS``).  Any save through :mod:`store` invalidates
the entry.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Tuple

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.schema import (
    ACTION_INVENTORY,
    EMPLOYEE_KEYS,
    RULE_CATEGORIES,
    default_rules_doc,
)


ResolvedRules = Dict[str, Any]


def _merge_dict_category(
    tenant_val: Dict[str, Any] | None,
    platform_val: Dict[str, Any],
    category: str,
    override_map: Dict[str, str],
) -> Dict[str, Any]:
    """Per-sub-field merge for dict-shaped categories.  Every key
    present in the platform default is emitted; the value is taken
    from the tenant when the tenant has an explicit entry, else
    from the platform.  Override map records each sub-field's
    source ``"tenant"`` or ``"platform"``.
    """
    out: Dict[str, Any] = {}
    tenant_val = tenant_val or {}
    for k, v_platform in platform_val.items():
        if isinstance(tenant_val, dict) and k in tenant_val:
            out[k] = tenant_val[k]
            override_map[f"{category}.{k}"] = "tenant"
        else:
            out[k] = copy.deepcopy(v_platform)
            override_map[f"{category}.{k}"] = "platform"
    # Any extra keys the tenant supplied (e.g. platform gained a new
    # action later — tenant preserved a stale one) are surfaced too
    # so a downstream migration can inspect them.  They count as
    # tenant overrides.
    if isinstance(tenant_val, dict):
        for k, v_tenant in tenant_val.items():
            if k not in out:
                out[k] = v_tenant
                override_map[f"{category}.{k}"] = "tenant"
    return out


def _merge_scalar_category(
    tenant_val: Any, platform_val: Any, category: str,
    override_map: Dict[str, str],
) -> Any:
    """Whole-object override for categories that don't split into
    resolvable sub-fields (``escalation_rules`` — an array —
    is atomic; ``working_hours`` sub-fields are merged separately)."""
    if tenant_val is not None:
        override_map[category] = "tenant"
        return copy.deepcopy(tenant_val)
    override_map[category] = "platform"
    return copy.deepcopy(platform_val)


async def resolve_rules_for_tenant(
    tenant_id: str, *, use_cache: bool = True,
    overlay: Dict[str, Any] | None = None,
) -> ResolvedRules:
    """Return the fully-resolved rules payload for ``tenant_id``.

    Cache-first — a fresh entry short-circuits the DB reads.  On a
    miss (or ``use_cache=False``), pulls the tenant doc + platform
    defaults, merges, caches, returns.

    ``overlay`` (MTH-D · Feb-2026) — optional per-category dict
    that is merged on top of the tenant's stored rules BEFORE the
    platform-defaults fallback.  Used by the ``preview`` endpoint
    to compute the shape of a rule change WITHOUT persisting it.
    An overlay ALWAYS bypasses the cache (both read and write) so
    a preview call cannot poison the shared 30-s cache.

    Response shape::

        {
          "tenant_id": "...",
          "master_ai_send_live_comms": bool,
          "rules": { ... resolved payload ... },
          "override_map": {
            "tone_voice.style": "tenant",
            "tone_voice.custom_directive": "platform",
            "working_hours.timezone": "tenant",
            "working_hours.windows": "platform",
            "escalation_rules": "platform",
            ...
          },
          "revision_number": int,
          "platform_revision_number": int,
          "last_updated_at": iso,
          "cached": bool,
          "overlay_applied": bool,
        }
    """
    has_overlay = bool(overlay)
    if use_cache and not has_overlay:
        cached = cache.get(tenant_id)
        if cached is not None:
            cached["cached"] = True
            cached["overlay_applied"] = False
            return cached

    tenant_doc = await store.get_tenant_rules(tenant_id)      # lazy-init OK
    platform_doc = await store.get_platform_defaults()
    platform_rules = platform_doc.get("rules") or default_rules_doc()
    tenant_rules = tenant_doc.get("rules") or {}

    # Apply the pending overlay ON TOP OF the stored tenant rules.
    # ``overlay`` is a category → value dict; the tenant's stored
    # value for each overlaid category is replaced wholesale (a
    # partial dict inside a category is still treated as an
    # explicit tenant override so the override_map reflects it).
    if has_overlay:
        tenant_rules = copy.deepcopy(tenant_rules)
        for cat_key, cat_val in (overlay or {}).items():
            if cat_key not in RULE_CATEGORIES:
                continue
            tenant_rules[cat_key] = copy.deepcopy(cat_val)

    override_map: Dict[str, str] = {}
    resolved: Dict[str, Any] = {}

    # tone_voice → dict-per-sub-field merge.
    resolved["tone_voice"] = _merge_dict_category(
        tenant_rules.get("tone_voice"),
        platform_rules.get("tone_voice", {}),
        "tone_voice", override_map,
    )
    # auto_action_allowlist → dict-per-action merge; every action
    # in ACTION_INVENTORY is guaranteed to appear at platform level
    # via default_rules_doc(), so the tenant-tier map's missing
    # actions fall back cleanly.
    resolved["auto_action_allowlist"] = _merge_dict_category(
        tenant_rules.get("auto_action_allowlist"),
        platform_rules.get("auto_action_allowlist", {}),
        "auto_action_allowlist", override_map,
    )
    # employee_enable_disable → dict-per-employee merge.
    resolved["employee_enable_disable"] = _merge_dict_category(
        tenant_rules.get("employee_enable_disable"),
        platform_rules.get("employee_enable_disable", {}),
        "employee_enable_disable", override_map,
    )
    # working_hours → dict-per-sub-field merge (enabled / timezone /
    # windows each resolve independently — a tenant can override the
    # windows list without also having to restate the timezone).
    resolved["working_hours"] = _merge_dict_category(
        tenant_rules.get("working_hours"),
        platform_rules.get("working_hours", {}),
        "working_hours", override_map,
    )
    # escalation_rules → whole-array atomic.  Merging two arrays of
    # unstructured rules would be surprising for admins.
    resolved["escalation_rules"] = _merge_scalar_category(
        tenant_rules.get("escalation_rules"),
        platform_rules.get("escalation_rules", []),
        "escalation_rules", override_map,
    )

    payload = {
        "tenant_id": tenant_id,
        "master_ai_send_live_comms": bool(
            tenant_doc.get("master_ai_send_live_comms", False),
        ),
        "rules": resolved,
        "override_map": override_map,
        "revision_number": int(
            tenant_doc.get("revision_number") or 0,
        ),
        "platform_revision_number": int(
            platform_doc.get("revision_number") or 0,
        ),
        "last_updated_at": tenant_doc.get("last_updated_at"),
        "cached": False,
        "overlay_applied": has_overlay,
    }
    if use_cache and not has_overlay:
        cache.set(tenant_id, payload)
    return payload
