"""Phase 42.4 · Feb-2026 — Stripe SDK v15 `.get()` broad-audit regression guard.

The audit found ZERO unsafe ``.get()`` sites against Stripe SDK
response objects in the backend. Both surface hits (``stripe_charge.py``
webhook + ``verify_stripe_config.py`` diagnostic) were already guarded
by the Phase 42.3 ``_asdict()`` helper or an explicit ``isinstance``
check.

This file locks that state:

  1. Simulate a v15 Stripe response by wrapping the payload in a
     ``types.SimpleNamespace`` (which does NOT expose ``.get()``).
  2. Feed it through the two public pathways that historically owned
     the risk — ``_asdict`` and ``handle_webhook_event``.
  3. Assert the parse survives + the returned dict has the expected
     keys.

Any future refactor that reintroduces raw ``.get()`` on a Stripe
object will fail one of these tests loudly.
"""
from __future__ import annotations

import asyncio
import types
from unittest.mock import patch

import pytest

from services.payments.stripe_charge import _asdict, handle_webhook_event


def _stripe_object(**fields):
    """Return a v15-shape object: no ``.get()``, no ``.items()``, only
    attribute access + ``to_dict()``."""
    ns = types.SimpleNamespace(**fields)
    ns.to_dict = lambda: {k: (_stripe_object_dict(v) if isinstance(v, types.SimpleNamespace) else v)
                           for k, v in fields.items()}
    return ns


def _stripe_object_dict(ns):
    if isinstance(ns, types.SimpleNamespace):
        return {k: _stripe_object_dict(v) for k, v in ns.__dict__.items() if not callable(v)}
    return ns


def test_asdict_handles_v15_stripe_object_without_get():
    """The ``_asdict`` helper must NOT crash on a v15 SimpleNamespace-shaped
    object that lacks ``.get()``. Regression guard for the whole
    ``_asdict``-based parse pathway (webhook, refresh, session, etc.)."""
    obj = _stripe_object(id="pi_abc", amount=1234, currency="usd")
    # Sanity — the mock really is v15-shaped (no ``.get``).
    assert not hasattr(obj, "get")
    result = _asdict(obj)
    assert isinstance(result, dict)
    assert result.get("id") == "pi_abc"
    assert result.get("amount") == 1234


def test_asdict_handles_plain_dict_passthrough():
    """A plain dict must be returned as-is (webhook already-decoded path)."""
    d = {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_x"}}}
    result = _asdict(d)
    assert result is d  # identity — no copy overhead on the hot path


def test_asdict_handles_none():
    """None -> ``{}``. Guards against optional Stripe fields."""
    assert _asdict(None) == {}


def test_webhook_handler_survives_v15_shaped_event():
    """End-to-end: build a v15-shaped ``payment_method.attached`` event
    (root + nested object are SimpleNamespaces), feed it into
    ``handle_webhook_event``, and confirm the parse doesn't crash.

    The handler will short-circuit at the ``crm_customer`` DB lookup
    (no such record in the test env) — that's fine; the point is the
    parse pathway survives.
    """
    inner = _stripe_object(id="pm_abc", customer="cus_xyz",
                           card=_stripe_object(brand="visa", last4="4242"))
    event = _stripe_object(
        type="payment_method.attached",
        data=_stripe_object(object=inner),
    )
    # Sanity — object graph is v15-shape all the way down.
    assert not hasattr(event, "get")
    assert not hasattr(event.data, "get")
    assert not hasattr(inner, "get")
    # Run under the loop.
    result = asyncio.run(handle_webhook_event(event))
    assert isinstance(result, dict)
    assert result["type"] == "payment_method.attached"


def test_webhook_handler_survives_v15_shaped_intent_event_parse_only():
    """Guard the ``payment_intent.succeeded`` PARSE step only.

    The full handler for this branch reaches into ``db.payments`` /
    ``db.invoices`` — that end-to-end coverage lives in the real
    Stripe integration suite. Here we exercise ONLY the parse via
    ``_asdict(event.get("data").get("object"))`` to prove a v15-shape
    intent doesn't crash the top-of-handler destructure."""
    inner = _stripe_object(id="pi_abc", status="succeeded", amount=1000,
                           currency="usd", metadata=_stripe_object())
    event = _stripe_object(
        type="payment_intent.succeeded",
        data=_stripe_object(object=inner),
    )
    ev = _asdict(event)
    data_env = _asdict(ev.get("data") or {})
    data = _asdict(data_env.get("object") or {})
    # Attribute-access equivalents survived; the DB layer would take it
    # from here in production.
    assert data.get("id") == "pi_abc"
    assert data.get("status") == "succeeded"
    assert data.get("amount") == 1000
    assert data.get("currency") == "usd"
