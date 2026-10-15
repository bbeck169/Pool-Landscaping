"""CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53) ·
``show_if`` conditional-logic engine on System A (Marketing Forms).

Pre-TD-53 all fields were unconditionally visible; a required-field
rule fired for every field tagged ``required=True`` regardless of
the submission context. TD-53 adds a sibling ``show_if`` rule on
``FormField`` that lets authors hide downstream fields until a parent
field's answer satisfies an operator predicate (``eq`` | ``neq`` |
``contains``). Hidden fields skip required-validation AND are
stripped from the submission payload before lead-extraction so the
lead row doesn't absorb stale answers from fields the submitter
never actually saw.

This suite exercises the engine at three layers:

  §1 · Save-time validator (``_validate_show_if_rules``) — rejects
       malformed rules (bad operator, dangling parent, self-ref,
       circular chain, missing value key).
  §2 · Runtime evaluator (``_is_field_visible``) — pure-function
       assertions on the ``eq`` / ``neq`` / ``contains`` operator
       semantics + ``None`` + empty-string coercion.
  §3 · Submit-endpoint integration — FastAPI AsyncClient against
       ``POST /widget/form/{fid}/submit`` to prove the visibility
       check actually suppresses the required-field 422 + strips
       hidden values from the persisted submission doc.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTtd53_"
TENANT = f"{PFX}tenant_A"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.marketing_forms.delete_many({"tenant_id": TENANT})
    await _DB.marketing_form_versions.delete_many({"tenant_id": TENANT})
    await _DB.form_submissions.delete_many({"tenant_id": TENANT})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


# ═══════════════════════════════════════════════════════════════════
# §1 · Save-time validator (_validate_show_if_rules)
# ═══════════════════════════════════════════════════════════════════


def _bad_operator_rejected():
    from routers.marketing_forms import FormField, _validate_field_defs
    fields = [
        FormField(label="Service", type="select", name="svc",
                  options=["pool", "landscape"]),
        FormField(label="Pool Size", type="text", name="pool_size",
                  show_if={"field_id": "svc", "operator": "startswith",
                            "value": "pool"}),
    ]
    with pytest.raises(HTTPException) as ei:
        _validate_field_defs(fields)
    assert ei.value.status_code == 422
    assert "show_if.operator" in str(ei.value.detail)


def test_show_if_rejects_unknown_operator():
    _bad_operator_rejected()


def test_show_if_rejects_dangling_parent_reference():
    from routers.marketing_forms import FormField, _validate_field_defs
    fields = [
        FormField(label="Pool Size", type="text", name="pool_size",
                  show_if={"field_id": "nonexistent",
                            "operator": "eq", "value": "pool"}),
    ]
    with pytest.raises(HTTPException) as ei:
        _validate_field_defs(fields)
    assert ei.value.status_code == 422
    assert "does not match any field" in str(ei.value.detail)


def test_show_if_rejects_self_reference():
    from routers.marketing_forms import FormField, _validate_field_defs
    fields = [
        FormField(label="Service", type="select", name="svc",
                  options=["pool"],
                  show_if={"field_id": "svc", "operator": "eq",
                            "value": "pool"}),
    ]
    with pytest.raises(HTTPException) as ei:
        _validate_field_defs(fields)
    assert ei.value.status_code == 422
    assert "cannot reference itself" in str(ei.value.detail)


def test_show_if_rejects_circular_chain():
    """A → B → A (and deeper A → B → C → A) rejected at save-time."""
    from routers.marketing_forms import FormField, _validate_field_defs
    fields = [
        FormField(label="A", type="text", name="a", id="a",
                  show_if={"field_id": "b", "operator": "eq",
                            "value": "x"}),
        FormField(label="B", type="text", name="b", id="b",
                  show_if={"field_id": "a", "operator": "eq",
                            "value": "y"}),
    ]
    with pytest.raises(HTTPException) as ei:
        _validate_field_defs(fields)
    assert ei.value.status_code == 422
    assert "circular" in str(ei.value.detail).lower()


def test_show_if_rejects_missing_value_key():
    from routers.marketing_forms import FormField, _validate_field_defs
    fields = [
        FormField(label="Service", type="select", name="svc",
                  options=["pool"]),
        FormField(label="Pool Size", type="text", name="pool_size",
                  show_if={"field_id": "svc", "operator": "eq"}),  # no "value"
    ]
    with pytest.raises(HTTPException) as ei:
        _validate_field_defs(fields)
    assert ei.value.status_code == 422
    assert "show_if.value" in str(ei.value.detail)


def test_show_if_rule_passes_through_on_valid_shape():
    from routers.marketing_forms import FormField, _validate_field_defs
    fields = [
        FormField(label="Service", type="select", name="svc",
                  options=["pool", "landscape"]),
        FormField(label="Pool Size", type="text", name="pool_size",
                  required=True,
                  show_if={"field_id": "svc", "operator": "eq",
                            "value": "pool"}),
    ]
    out = _validate_field_defs(fields)
    assert len(out) == 2
    assert out[1]["show_if"]["operator"] == "eq"
    assert out[1]["show_if"]["field_id"] == "svc"


# ═══════════════════════════════════════════════════════════════════
# §2 · Runtime evaluator (_is_field_visible)
# ═══════════════════════════════════════════════════════════════════


def _mk_fields_and_lookup(child_rule: Optional[Dict[str, Any]]):
    """Build a 2-field schema (parent ``svc`` + child ``pool_size``)
    + id-lookup, with the child carrying the given ``show_if`` rule."""
    parent = {"id": "svc", "name": "svc", "label": "Service",
              "type": "select"}
    child = {"id": "pool_size", "name": "pool_size", "label": "Pool Size",
             "type": "text", "show_if": child_rule}
    return [parent, child], {"svc": parent, "pool_size": child}


def test_eval_eq_visible_when_parent_matches():
    from routers.marketing_forms import _is_field_visible
    _, lookup = _mk_fields_and_lookup(
        {"field_id": "svc", "operator": "eq", "value": "pool"},
    )
    assert _is_field_visible(lookup["pool_size"], {"svc": "pool"}, lookup) is True
    assert _is_field_visible(lookup["pool_size"], {"svc": "landscape"}, lookup) is False
    # Pre-TD-53 forms (no rule) always visible.
    _, lookup2 = _mk_fields_and_lookup(None)
    assert _is_field_visible(lookup2["pool_size"], {"svc": "anything"}, lookup2) is True


def test_eval_neq_is_inverse_of_eq():
    from routers.marketing_forms import _is_field_visible
    _, lookup = _mk_fields_and_lookup(
        {"field_id": "svc", "operator": "neq", "value": "pool"},
    )
    assert _is_field_visible(lookup["pool_size"], {"svc": "pool"}, lookup) is False
    assert _is_field_visible(lookup["pool_size"], {"svc": "landscape"}, lookup) is True


def test_eval_contains_handles_list_and_string_parents():
    from routers.marketing_forms import _is_field_visible
    _, lookup = _mk_fields_and_lookup(
        {"field_id": "svc", "operator": "contains", "value": "pool"},
    )
    # List/multiselect parent: value must be a member.
    assert _is_field_visible(
        lookup["pool_size"], {"svc": ["pool", "spa"]}, lookup,
    ) is True
    assert _is_field_visible(
        lookup["pool_size"], {"svc": ["spa", "patio"]}, lookup,
    ) is False
    # String parent: substring match.
    assert _is_field_visible(
        lookup["pool_size"], {"svc": "swimming-pool-maintenance"}, lookup,
    ) is True
    assert _is_field_visible(
        lookup["pool_size"], {"svc": "landscape-work"}, lookup,
    ) is False
    # Defensive — numeric parent + string target → False.
    assert _is_field_visible(
        lookup["pool_size"], {"svc": 42}, lookup,
    ) is False


def test_eval_empty_string_coerces_to_none_for_eq():
    """A field answered with empty string compares equal to a
    never-answered field — both coerce to None under _coerce_for_compare."""
    from routers.marketing_forms import _is_field_visible
    _, lookup = _mk_fields_and_lookup(
        {"field_id": "svc", "operator": "eq", "value": None},
    )
    assert _is_field_visible(lookup["pool_size"], {"svc": ""}, lookup) is True
    assert _is_field_visible(lookup["pool_size"], {"svc": "   "}, lookup) is True
    assert _is_field_visible(lookup["pool_size"], {}, lookup) is True
    assert _is_field_visible(lookup["pool_size"], {"svc": "pool"}, lookup) is False


# ═══════════════════════════════════════════════════════════════════
# §3 · Submit-endpoint integration — required-skip + value-strip
# ═══════════════════════════════════════════════════════════════════


async def _seed_form(fields: List[Dict[str, Any]]) -> str:
    """Insert a marketing form doc directly (bypasses the admin API
    for speed). Returns the form id. Submission tests then POST to
    ``/widget/form/{fid}/submit``."""
    fid = f"{PFX}form_{uuid.uuid4().hex[:10]}"
    await _DB.marketing_forms.insert_one({
        "id": fid, "tenant_id": TENANT,
        "name": "TD-53 Form", "slug": fid,
        "active": True,
        "fields": fields,
        "submit_config": {"creates": "lead", "admin_bell": False},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return fid


def _build_submit_app() -> FastAPI:
    """Mount ``routers.marketing_forms.router`` under ``/api`` with a
    tenant-override for the widget-auth dependency so the submit path
    runs against the test DB without a real widget key."""
    from routers import marketing_forms as mf
    mf.db = _DB
    app = FastAPI()
    app.include_router(mf.router)
    app.dependency_overrides[mf.require_widget_auth] = lambda: {"id": TENANT}
    # Short-circuit Turnstile — _verify_turnstile reads TURNSTILE_SECRET
    # at call time; set a sentinel in the module's cached state so it
    # bypasses in test mode.
    mf._verify_turnstile = _bypass_turnstile  # type: ignore[assignment]
    return app


async def _bypass_turnstile(*_a, **_k):
    """Replacement for ``_verify_turnstile`` that always passes."""
    return None


async def _submit(fid: str, answers: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    app = _build_submit_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/widget/form/{fid}/submit", json={"answers": answers})
    body = r.json() if r.content else {}
    return r.status_code, body


def test_hidden_required_field_does_not_trigger_422():
    """Field marked ``required=True`` is HIDDEN by ``show_if`` →
    submission must succeed WITHOUT answering it. This is the core
    TD-53 pay-off: authors can make a field "required when visible"
    without needing a parallel JS validator on the FE."""
    fid = _run(_seed_form([
        {"id": "svc", "name": "svc", "label": "Service",
         "type": "select", "options": ["pool", "landscape"], "order": 0},
        {"id": "pool_size", "name": "pool_size", "label": "Pool Size",
         "type": "text", "required": True, "order": 1,
         "show_if": {"field_id": "svc", "operator": "eq", "value": "pool"}},
    ]))
    # svc=landscape → pool_size hidden → no 422 even though required.
    status, body = _run(_submit(fid, {"svc": "landscape"}))
    assert status == 201, f"expected 201 but got {status}: {body}"


def test_visible_required_field_still_triggers_422():
    """Regression guard: when the show_if rule EVALUATES TRUE, the
    field IS visible and required-check still fires. Otherwise TD-53
    would effectively nullify required-validation for every field."""
    fid = _run(_seed_form([
        {"id": "svc", "name": "svc", "label": "Service",
         "type": "select", "options": ["pool", "landscape"], "order": 0},
        {"id": "pool_size", "name": "pool_size", "label": "Pool Size",
         "type": "text", "required": True, "order": 1,
         "show_if": {"field_id": "svc", "operator": "eq", "value": "pool"}},
    ]))
    # svc=pool → pool_size visible → missing answer → 422.
    status, body = _run(_submit(fid, {"svc": "pool"}))
    assert status == 422
    assert "missing required fields" in str(body.get("detail", "")).lower()
    assert "pool_size" in str(body.get("detail", ""))


def test_hidden_field_value_stripped_from_persisted_submission():
    """Even if the client POSTs a stale value for a hidden field
    (e.g. user filled it, then changed svc and the FE didn't scrub),
    the server strips it before persistence so the lead-extraction
    pipeline + the audit trail reflect only the operator-visible
    state."""
    fid = _run(_seed_form([
        {"id": "svc", "name": "svc", "label": "Service",
         "type": "select", "options": ["pool", "landscape"], "order": 0},
        {"id": "pool_size", "name": "pool_size", "label": "Pool Size",
         "type": "text", "order": 1,
         "show_if": {"field_id": "svc", "operator": "eq", "value": "pool"}},
    ]))
    status, body = _run(_submit(fid, {
        "svc": "landscape",
        "pool_size": "20x40 (stale answer from before user switched svc)",
    }))
    assert status == 201
    # Confirm the persisted doc dropped the hidden field.
    sub = _run(_DB.form_submissions.find_one({"id": body["submission_id"]}))
    assert "pool_size" not in (sub.get("answers") or {})
    assert sub.get("answers", {}).get("svc") == "landscape"


def test_legacy_form_without_show_if_round_trips_byte_identical():
    """Byte-identical regression guard: a form with NO show_if rule
    on any field behaves exactly as pre-TD-53 — required-check fires
    normally, no payload stripping occurs."""
    fid = _run(_seed_form([
        {"id": "name", "name": "name", "label": "Name",
         "type": "text", "required": True, "order": 0},
        {"id": "email", "name": "email", "label": "Email",
         "type": "email", "required": True, "order": 1},
    ]))
    # Missing both → 422 (same as pre-TD-53).
    status, body = _run(_submit(fid, {}))
    assert status == 422
    assert "name" in str(body.get("detail", ""))
    assert "email" in str(body.get("detail", ""))
    # Full answers → 201 (same as pre-TD-53).
    status, body = _run(_submit(fid, {
        "name": "Jane", "email": "j@x.com",
    }))
    assert status == 201
    sub = _run(_DB.form_submissions.find_one({"id": body["submission_id"]}))
    # Every answered field persisted — no stripping.
    assert sub["answers"] == {"name": "Jane", "email": "j@x.com"}
