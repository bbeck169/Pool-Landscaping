"""QuoteIQ Phase Q2 — AI Estimator service.

Wraps the Emergent LLM call, injects the tenant's service catalog +
price book into the system prompt, enforces JSON-only response format,
and validates the shape before returning.

Test mode: set ``TEST_LLM_MOCK=1`` to bypass the network call and
return a deterministic 3-line-item response (or 3-tier if
``options_mode=True``). Same code path is exercised in tests.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from config import db, logger, EMERGENT_LLM_KEY
from utils import new_id


DEFAULT_MODEL_PROVIDER = "anthropic"
DEFAULT_MODEL_NAME = "claude-sonnet-4-5"


def _mock_enabled() -> bool:
    return (os.environ.get("TEST_LLM_MOCK") or "").strip() in ("1", "true", "yes")


def _mock_response(*, options_mode: bool) -> Dict[str, Any]:
    """Deterministic mock. Shape matches the LLM contract exactly."""
    if options_mode:
        return {
            "tiers": [
                {
                    "name": "Basic",
                    "description": "Weekly chemistry + skim + brush.",
                    "line_items": [
                        {"sku": "SVC-WKLY", "service_slug": "weekly_service",
                          "description": "Weekly maintenance visit",
                          "qty": 4, "unit": "visit", "unit_price_cents": 12500,
                          "source": "catalog", "confidence": 0.95},
                        {"sku": None, "service_slug": None,
                          "description": "Chlorine + acid included",
                          "qty": 1, "unit": "month", "unit_price_cents": 4500,
                          "source": "ai_inferred", "confidence": 0.7},
                    ],
                },
                {
                    "name": "Standard",
                    "description": "Basic + filter clean + salt check.",
                    "line_items": [
                        {"sku": "SVC-WKLY", "service_slug": "weekly_service",
                          "description": "Weekly maintenance visit",
                          "qty": 4, "unit": "visit", "unit_price_cents": 12500,
                          "source": "catalog", "confidence": 0.95},
                        {"sku": "SVC-FILTER", "service_slug": "filter_clean",
                          "description": "Monthly filter cleaning",
                          "qty": 1, "unit": "clean", "unit_price_cents": 8500,
                          "source": "catalog", "confidence": 0.9},
                    ],
                },
                {
                    "name": "Premium",
                    "description": "Standard + equipment inspection + priority.",
                    "line_items": [
                        {"sku": "SVC-WKLY", "service_slug": "weekly_service",
                          "description": "Weekly maintenance visit",
                          "qty": 4, "unit": "visit", "unit_price_cents": 12500,
                          "source": "catalog", "confidence": 0.95},
                        {"sku": "SVC-INSPECT", "service_slug": "equipment_inspection",
                          "description": "Monthly equipment inspection",
                          "qty": 1, "unit": "visit", "unit_price_cents": 12000,
                          "source": "catalog", "confidence": 0.85},
                        {"sku": None, "service_slug": None,
                          "description": "Priority scheduling surcharge",
                          "qty": 1, "unit": "month", "unit_price_cents": 5000,
                          "source": "ai_inferred", "confidence": 0.6},
                    ],
                },
            ],
            "notes": "Mocked response — TEST_LLM_MOCK=1.",
        }
    return {
        "line_items": [
            {"sku": "SVC-WKLY", "service_slug": "weekly_service",
              "description": "Weekly maintenance visit",
              "qty": 4, "unit": "visit", "unit_price_cents": 12500,
              "source": "catalog", "confidence": 0.95},
            {"sku": "CHEM-CHLOR", "service_slug": "chlorine_add",
              "description": "Liquid chlorine dosing per visit",
              "qty": 4, "unit": "gal", "unit_price_cents": 450,
              "source": "catalog", "confidence": 0.9},
            {"sku": None, "service_slug": None,
              "description": "Debris clearing (observed in photos)",
              "qty": 1, "unit": "job", "unit_price_cents": 7500,
              "source": "ai_inferred", "confidence": 0.7},
        ],
        "notes": "Mocked response — TEST_LLM_MOCK=1.",
    }


async def _load_catalog(tenant_id: str) -> List[Dict[str, Any]]:
    """Load the tenant's chemical catalog + any active service catalog rows.
    Returns a lightweight list the LLM can reason about."""
    rows: List[Dict[str, Any]] = []
    async for r in db.chemical_costs.find({"tenant_id": tenant_id}, {"_id": 0}):
        if r.get("active") is False:
            continue
        rows.append({
            "sku": r.get("sku") or r.get("chemical_slug"),
            "service_slug": r.get("chemical_slug"),
            "name": r.get("name"),
            "unit": r.get("unit_kind"),
            "unit_price_cents": int(r.get("cost_per_unit_cents") or 0),
            "kind": "chemical",
        })
    # Include estimate line-item templates as service catalog fallback.
    async for r in db.estimate_templates.find({"tenant_id": tenant_id}, {"_id": 0}).limit(50):
        rows.append({
            "sku": r.get("id"),
            "service_slug": r.get("name", "").lower().replace(" ", "_"),
            "name": r.get("name"),
            "unit_price_cents": int((r.get("line_items") or [{}])[0].get("unit_cost", 0) * 100),
            "kind": "template",
        })
    return rows


def _build_system_prompt(catalog: List[Dict[str, Any]],
                          options_mode: bool) -> str:
    catalog_txt = json.dumps(catalog[:80], separators=(",", ":"))
    base = (
        "You are the AI Estimator for a pool & landscape service company. "
        "Given photos and a job description, produce a line-itemized estimate.\n\n"
        f"Tenant catalog (use catalog SKUs when possible, mark source=catalog): {catalog_txt}\n\n"
        "Output STRICT JSON. Do not include any text outside the JSON block. "
        "Every line item MUST have: description, qty, unit, unit_price_cents (integer), source ('catalog' or 'ai_inferred'), confidence (0..1). "
        "Prefer catalog items and snap unit_price_cents to their exact value. Only invent unit_price_cents when source='ai_inferred'.\n"
    )
    if options_mode:
        return base + (
            'Return: {"tiers":[{"name":"Basic","description":"…","line_items":[…]},'
            '{"name":"Standard","description":"…","line_items":[…]},'
            '{"name":"Premium","description":"…","line_items":[…]}],"notes":"…"}\n'
            "The 3 tiers must have clear differentiators (scope, frequency, chemicals, equipment)."
        )
    return base + (
        'Return: {"line_items":[{...}, ...], "notes":"…"}'
    )


def _validate_response(raw: Dict[str, Any], *, options_mode: bool
                        ) -> Dict[str, Any]:
    """Validate + normalize the LLM JSON. Raises ValueError on bad shape."""
    if options_mode:
        tiers = raw.get("tiers")
        if not isinstance(tiers, list) or len(tiers) < 1:
            raise ValueError("response missing tiers[]")
        norm_tiers = []
        for t in tiers[:3]:
            items = t.get("line_items") or []
            norm_items = [_normalize_line(li) for li in items if isinstance(li, dict)]
            norm_tiers.append({
                "id": new_id(),
                "name": str(t.get("name") or "Tier"),
                "description": str(t.get("description") or ""),
                "line_items": norm_items,
                "total_cents": sum(li["subtotal_cents"] for li in norm_items),
                "is_default": False,
            })
        if norm_tiers:
            # Default to the middle tier if present, else the first.
            default_idx = min(len(norm_tiers) - 1, 1)
            norm_tiers[default_idx]["is_default"] = True
        return {"tiers": norm_tiers, "notes": str(raw.get("notes") or "")}
    items = raw.get("line_items")
    if not isinstance(items, list) or not items:
        raise ValueError("response missing line_items[]")
    norm = [_normalize_line(li) for li in items if isinstance(li, dict)]
    return {"line_items": norm, "notes": str(raw.get("notes") or "")}


def _normalize_line(li: Dict[str, Any]) -> Dict[str, Any]:
    try:
        qty = float(li.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    try:
        unit_price = int(li.get("unit_price_cents") or 0)
    except (TypeError, ValueError):
        unit_price = 0
    source = str(li.get("source") or "ai_inferred").lower()
    if source not in ("catalog", "ai_inferred"):
        source = "ai_inferred"
    return {
        "sku": li.get("sku"),
        "service_slug": li.get("service_slug"),
        "description": str(li.get("description") or ""),
        "qty": qty,
        "unit": str(li.get("unit") or "each"),
        "unit_price_cents": unit_price,
        "subtotal_cents": int(round(qty * unit_price)),
        "source": source,
        "confidence": float(li.get("confidence") or 0.5),
    }


async def _snap_to_catalog(tenant_id: str, items: List[Dict[str, Any]]
                             ) -> List[Dict[str, Any]]:
    """For every ``source='catalog'`` line, verify the SKU exists and
    replace ``unit_price_cents`` with the current catalog value. Rows
    with unknown SKUs demote to ``source='ai_inferred'`` so downstream
    code doesn't trust an unauthorized catalog price."""
    known: Dict[str, Dict[str, Any]] = {}
    async for r in db.chemical_costs.find({"tenant_id": tenant_id}, {"_id": 0}):
        slug = str(r.get("chemical_slug") or "").lower()
        sku = str(r.get("sku") or "").lower()
        if slug:
            known[slug] = r
        if sku:
            known[sku] = r
    out = []
    for li in items:
        if li["source"] == "catalog":
            key = str(li.get("service_slug") or li.get("sku") or "").lower()
            row = known.get(key)
            if row:
                li["unit_price_cents"] = int(row.get("cost_per_unit_cents") or li["unit_price_cents"])
                li["subtotal_cents"] = int(round(li["qty"] * li["unit_price_cents"]))
            else:
                li["source"] = "ai_inferred"
        out.append(li)
    return out


def _has_zero_lines(items: List[Dict[str, Any]]) -> bool:
    """Any line item with qty * unit_price_cents == 0 (or missing) is
    treated as invalid. Retry / fallback logic uses this signal."""
    if not items:
        return True
    for li in items:
        qty = float(li.get("qty") or 0)
        unit = int(li.get("unit_price_cents") or 0)
        sub = int(li.get("subtotal_cents") or 0)
        if qty <= 0 or unit <= 0 or sub <= 0:
            return True
    return False


def _result_has_zero(result: Dict[str, Any], *, options_mode: bool) -> bool:
    """True if ANY tier/line-items entry contains a $0-total line, or
    if the aggregate total is zero. Drives the retry decision."""
    if options_mode:
        for t in result.get("tiers") or []:
            if _has_zero_lines(t.get("line_items") or []):
                return True
            if int(t.get("total_cents") or 0) <= 0:
                return True
        return False
    items = result.get("line_items") or []
    if _has_zero_lines(items):
        return True
    if sum(int(li.get("subtotal_cents") or 0) for li in items) <= 0:
        return True
    return False


def _catalog_only_fallback(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Last-resort filter — keep only line-items that came from the
    tenant catalog (post-``_snap_to_catalog``) AND have a positive
    subtotal. Everything else is dropped so no $0 line ever leaks to
    the user. If nothing survives the callers surface an empty list
    with a specific error code."""
    kept = []
    for li in items:
        if li.get("source") != "catalog":
            continue
        if float(li.get("qty") or 0) <= 0:
            continue
        if int(li.get("unit_price_cents") or 0) <= 0:
            continue
        kept.append(li)
    return kept


ZERO_RETRY_HINT = (
    "The previous response contained one or more zero-valued line "
    "items — this is not acceptable. Every line_item MUST have "
    "qty > 0 and unit_price_cents > 0. subtotal_cents MUST equal "
    "qty * unit_price_cents. Do not include any zero-cost or "
    "zero-quantity rows. Re-emit the JSON with valid numbers."
)


async def _call_llm(*, system_prompt: str, job_description: str,
                      photo_urls: Optional[List[str]] = None,
                      extras: Optional[Dict[str, Any]] = None,
                      extra_user_hint: str = "",
                      tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Single LLM round-trip via the shared ``llm_provider`` dispatcher.

    Returns ``{"raw": <parsed json>, "provider": "emergent"|"openai"|"tenant_byo"}``
    on success or ``{"error": "..."}`` on failure. When
    ``tenant_id`` is passed and the tenant BYO monthly cap is
    exceeded, returns ``{"error": "ai_spend_cap_exceeded",
    "cap_exceeded": True, "provider": "tenant_byo"}`` — caller
    surfaces to router which raises HTTP 429. Provider tag flows
    up into ``_meta`` so downstream persistence knows who served
    the request.

    Phase I1.7.e · chunk 2.c · Feb-2026 — Threads ``tenant_id``
    into ``call_llm_with_fallback`` for tenant-BYO provider
    routing + per-tenant AI cap enforcement.
    """
    from services.llm_provider import call_llm_with_fallback
    parts: List[str] = [f"Job description: {job_description}"]
    if extras:
        parts.append(f"Context: {json.dumps(extras)}")
    if extra_user_hint:
        parts.append(extra_user_hint)
    user_text = "\n".join(parts)
    r = await call_llm_with_fallback(
        system_prompt=system_prompt,
        user_text=user_text,
        photo_urls=photo_urls,
        provider=DEFAULT_MODEL_PROVIDER,
        model=DEFAULT_MODEL_NAME,
        tenant_id=tenant_id,
    )
    if r.get("error"):
        return {"error": r["error"], "provider": r.get("provider"),
                "cap_exceeded": bool(r.get("cap_exceeded"))}
    return {"raw": r["raw"], "provider": r.get("provider")}


async def _finalize(tenant_id: str, raw: Dict[str, Any], *,
                      options_mode: bool) -> Dict[str, Any]:
    """Validate → catalog-snap → recompute totals. Returns the result
    dict ready for the caller."""
    try:
        result = _validate_response(raw, options_mode=options_mode)
    except ValueError as e:
        return {"error": f"invalid_response: {e}", "line_items": []}
    if options_mode:
        for t in result["tiers"]:
            t["line_items"] = await _snap_to_catalog(tenant_id, t["line_items"])
            t["total_cents"] = sum(li["subtotal_cents"] for li in t["line_items"])
    else:
        result["line_items"] = await _snap_to_catalog(
            tenant_id, result["line_items"])
    return result


async def generate_estimate(*, tenant_id: str,
                              photo_urls: List[str],
                              job_description: str,
                              options_mode: bool = False,
                              extras: Optional[Dict[str, Any]] = None
                              ) -> Dict[str, Any]:
    """High-level entrypoint used by the router. Returns the validated
    + catalog-snapped result dict. Never raises for LLM failures — on
    error returns ``{"error": "...", "line_items": []}`` so callers can
    log ``status="error"`` without a 500.

    Q3-hardening: if the LLM emits any $0 line item (qty=0 OR
    unit_price=0 OR subtotal=0), we retry once with an explicit
    reformat hint. If the retry still produces $0 lines, we fall
    back to a catalog-only pass — dropping any non-catalog $0 rows and
    keeping only line items that map to real tenant catalog entries.
    ``_meta`` on the returned dict tells the router which path ran.
    """
    catalog = await _load_catalog(tenant_id)
    system_prompt = _build_system_prompt(catalog, options_mode)

    if _mock_enabled():
        # Test-only injection: allow overriding the mock response so
        # unit tests can force the retry / fallback branches without
        # burning real-LLM quota. See ``services.ai_estimator._TEST_MOCK_OVERRIDES``.
        raw = _next_test_mock(options_mode=options_mode) \
            or _mock_response(options_mode=options_mode)
        result = await _finalize(tenant_id, raw, options_mode=options_mode)
        # Even in mock mode, honour the retry/fallback contract so tests
        # exercise the same code path as prod.
        meta = {"path": "mock_ok", "retries": 0, "provider": "mock"}
        if _result_has_zero(result, options_mode=options_mode):
            raw2 = _next_test_mock(options_mode=options_mode)
            if raw2:
                result = await _finalize(tenant_id, raw2,
                                            options_mode=options_mode)
            meta["retries"] = 1
            if _result_has_zero(result, options_mode=options_mode):
                result = _apply_catalog_fallback(result, options_mode=options_mode)
                meta["path"] = "catalog_fallback"
                meta["provider"] = "catalog_fallback"
            else:
                meta["path"] = "mock_retry_ok"
        result["_meta"] = meta
        return result

    # Real-LLM path -------------------------------------------------------
    first = await _call_llm(system_prompt=system_prompt,
                              job_description=job_description,
                              photo_urls=photo_urls, extras=extras,
                              tenant_id=tenant_id)
    if first.get("cap_exceeded"):
        # Phase I1.7.e · chunk 2.c · Feb-2026 — surface cap-exceeded
        # verbatim so the router can raise HTTP 429 via
        # ``services.ai.cap_http.raise_if_ai_cap_exceeded``. No retry,
        # no catalog fallback — the tenant hit their monthly BYO cap.
        return {"error": "ai_spend_cap_exceeded", "line_items": [],
                 "cap_exceeded": True,
                 "_meta": {"path": "cap_exceeded", "retries": 0,
                            "provider": first.get("provider") or "tenant_byo"}}
    if first.get("error"):
        return {"error": first["error"], "line_items": [],
                 "_meta": {"path": "llm_error", "retries": 0,
                            "provider": first.get("provider")}}
    result = await _finalize(tenant_id, first["raw"], options_mode=options_mode)
    if result.get("error"):
        result["_meta"] = {"path": "llm_invalid_response", "retries": 0,
                             "provider": first.get("provider")}
        return result
    meta = {"path": "llm_ok", "retries": 0, "provider": first.get("provider")}
    if _result_has_zero(result, options_mode=options_mode):
        # Retry once with an explicit reformat hint.
        second = await _call_llm(system_prompt=system_prompt,
                                    job_description=job_description,
                                    photo_urls=photo_urls, extras=extras,
                                    extra_user_hint=ZERO_RETRY_HINT,
                                    tenant_id=tenant_id)
        meta["retries"] = 1
        if second.get("cap_exceeded"):
            # Retry hit the cap — bail with cap-exceeded semantics.
            return {"error": "ai_spend_cap_exceeded", "line_items": [],
                     "cap_exceeded": True,
                     "_meta": {"path": "cap_exceeded", "retries": 1,
                                "provider": second.get("provider") or "tenant_byo"}}
        if not second.get("error"):
            retry_result = await _finalize(tenant_id, second["raw"],
                                              options_mode=options_mode)
            if not retry_result.get("error") and not _result_has_zero(
                    retry_result, options_mode=options_mode):
                retry_result["_meta"] = {
                    "path": "llm_retry_ok", "retries": 1,
                    "provider": second.get("provider"),
                }
                return retry_result
            result = retry_result if not retry_result.get("error") else result
            # Retry provider tag wins when it produced parseable JSON.
            if not retry_result.get("error"):
                meta["provider"] = second.get("provider")
        # Retry still bad → catalog-only fallback.
        result = _apply_catalog_fallback(result, options_mode=options_mode)
        meta["path"] = "catalog_fallback"
        # Catalog fallback path means the provider tag is
        # informational — flip to ``catalog_fallback`` so downstream
        # can tell "we didn't trust the LLM output".
        meta["provider"] = meta.get("provider") or "catalog_fallback"
    result["_meta"] = meta
    return result


def _apply_catalog_fallback(result: Dict[str, Any], *,
                              options_mode: bool) -> Dict[str, Any]:
    """Drop $0 lines + non-catalog rows across a normalized result."""
    if options_mode:
        for t in result.get("tiers") or []:
            t["line_items"] = _catalog_only_fallback(t.get("line_items") or [])
            t["total_cents"] = sum(li["subtotal_cents"] for li in t["line_items"])
    else:
        result["line_items"] = _catalog_only_fallback(
            result.get("line_items") or [])
    return result


# Test-only queue of mock overrides. Populated by tests via
# ``prime_test_mocks(...)`` to exercise the retry / fallback branches
# deterministically. Never touched in production code paths.
_TEST_MOCK_OVERRIDES: List[Dict[str, Any]] = []


def prime_test_mocks(*payloads: Dict[str, Any]) -> None:
    """Queue N mock payloads. ``generate_estimate`` will consume them in
    order (one per call) instead of the default mock response."""
    _TEST_MOCK_OVERRIDES.extend(payloads)


def clear_test_mocks() -> None:
    _TEST_MOCK_OVERRIDES.clear()


def _next_test_mock(*, options_mode: bool) -> Optional[Dict[str, Any]]:
    if _TEST_MOCK_OVERRIDES:
        return _TEST_MOCK_OVERRIDES.pop(0)
    return None
