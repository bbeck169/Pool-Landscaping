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


async def generate_estimate(*, tenant_id: str,
                              photo_urls: List[str],
                              job_description: str,
                              options_mode: bool = False,
                              extras: Optional[Dict[str, Any]] = None
                              ) -> Dict[str, Any]:
    """High-level entrypoint used by the router. Returns the validated
    + catalog-snapped result dict. Never raises for LLM failures — on
    error returns ``{"error": "...", "line_items": []}`` so callers can
    log ``status="error"`` without a 500."""
    catalog = await _load_catalog(tenant_id)
    if _mock_enabled():
        raw = _mock_response(options_mode=options_mode)
    else:
        key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
        if not key:
            return {"error": "EMERGENT_LLM_KEY missing — set env or TEST_LLM_MOCK=1",
                    "line_items": []}
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        except Exception as e:
            return {"error": f"emergentintegrations import failed: {e}",
                    "line_items": []}
        try:
            system_prompt = _build_system_prompt(catalog, options_mode)
            chat = (LlmChat(api_key=key, session_id=new_id(),
                             system_message=system_prompt)
                    .with_model(DEFAULT_MODEL_PROVIDER, DEFAULT_MODEL_NAME))
            content_parts: List[Any] = [f"Job description: {job_description}"]
            if extras:
                content_parts.append(f"Context: {json.dumps(extras)}")
            for url in (photo_urls or [])[:8]:
                try:
                    content_parts.append(ImageContent(image_url=url))
                except Exception:
                    pass
            msg = UserMessage(text="\n".join(str(p) for p in content_parts
                                              if isinstance(p, str)))
            resp = await chat.send_message(msg)
            raw_text = str(resp).strip()
            # Extract the first JSON object in case the model wraps it in prose.
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            payload = json.loads(raw_text[start:end + 1]) if start >= 0 else {}
            raw = payload
        except Exception as e:
            logger.warning(f"[ai_estimator] LLM call failed: {e}")
            return {"error": f"llm_call_failed: {e}", "line_items": []}

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
