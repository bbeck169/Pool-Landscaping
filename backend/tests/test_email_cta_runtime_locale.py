"""Feb 2026 · Invoice Email CTA Label — RUNTIME locale wiring tests.

Covers the tester follow-up gap: even though the block functions
accept ``locale``, the send path in ``routers/comms.py::
deliver_one_by_ids`` was reading the frozen English ``blocks_json``
from the DB template. The runtime rebuild helper
``_apply_runtime_locale_to_invoice_template`` was added to swap the
frozen blocks with a freshly-rebuilt localised copy per recipient
locale — this file locks that behaviour in.

Follows the Feb 2026 baseline (async unit tests + no real Mongo).
Tests target the small helper directly + the outer
``deliver_one_by_ids`` via a Motor-shaped in-memory stub, so no
preview state is mutated and no HTTP round-trip is required.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch


def _run(coro):
    return asyncio.run(coro)


# ─── The frozen ``blocks_json`` shape we simulate coming out of Mongo ─
def _english_invoice_created_blocks() -> list:
    """Freeze a shape identical to what the seed_comms path writes."""
    from comms_seed.system_data import _invoice_created_blocks
    return _invoice_created_blocks("en")


def _english_invoice_overdue_blocks() -> list:
    from comms_seed.system_data import _invoice_overdue_blocks
    return _invoice_overdue_blocks("en")


def _tpl(code: str, blocks: list, *, is_system: bool = True) -> Dict[str, Any]:
    return {
        "code": code,
        "tenant_id": None,
        "is_system": is_system,
        "subject": "Invoice ready",
        "blocks_json": blocks,
    }


def _find_button_label(blocks: list) -> str:
    for b in blocks:
        if b.get("type") == "button":
            return b.get("props", {}).get("label")
    return ""


# ═══════════════════════════════════════════════════════════════════
# 1 · _apply_runtime_locale_to_invoice_template — direct unit tests
# ═══════════════════════════════════════════════════════════════════

def test_runtime_locale_swap_english_customer_keeps_english_label():
    from routers.comms import _apply_runtime_locale_to_invoice_template
    tpl = _tpl("system.invoice_created", _english_invoice_created_blocks())
    customer = {"id": "c1", "locale": "en"}
    tenant = {"id": "t1", "default_locale": "en"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_created", customer, tenant,
    )
    assert _find_button_label(out["blocks_json"]) == "View Invoice"


def test_runtime_locale_swap_spanish_customer_renders_ver_factura():
    from routers.comms import _apply_runtime_locale_to_invoice_template
    tpl = _tpl("system.invoice_created", _english_invoice_created_blocks())
    customer = {"id": "c1", "locale": "es"}
    tenant = {"id": "t1", "default_locale": "en"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_created", customer, tenant,
    )
    assert _find_button_label(out["blocks_json"]) == "Ver factura"


def test_runtime_locale_swap_french_customer_renders_voir_la_facture():
    from routers.comms import _apply_runtime_locale_to_invoice_template
    tpl = _tpl("system.invoice_overdue", _english_invoice_overdue_blocks())
    customer = {"id": "c1", "locale": "fr"}
    tenant = {"id": "t1", "default_locale": "en"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_overdue", customer, tenant,
    )
    assert _find_button_label(out["blocks_json"]) == "Voir la facture"


def test_runtime_locale_swap_falls_back_to_tenant_default_locale():
    """Customer has no locale → resolver falls through to tenant's
    ``default_locale``. This is the priority order documented on
    :func:`resolve_recipient_locale`."""
    from routers.comms import _apply_runtime_locale_to_invoice_template
    tpl = _tpl("system.invoice_created", _english_invoice_created_blocks())
    customer = {"id": "c1"}  # no locale
    tenant = {"id": "t1", "default_locale": "fr"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_created", customer, tenant,
    )
    assert _find_button_label(out["blocks_json"]) == "Voir la facture"


def test_runtime_locale_swap_falls_back_to_english_when_no_locale_anywhere():
    from routers.comms import _apply_runtime_locale_to_invoice_template
    tpl = _tpl("system.invoice_created", _english_invoice_created_blocks())
    customer = {"id": "c1"}
    tenant = {"id": "t1"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_created", customer, tenant,
    )
    assert _find_button_label(out["blocks_json"]) == "View Invoice"


def test_runtime_locale_swap_ignores_non_invoice_templates():
    """A non-invoice template code (welcome, visit summary, etc.)
    must NOT get rebuilt — those are locale-invariant for this ticket
    and rewriting them would silently break tenants who have edited
    the copy in-place."""
    from routers.comms import _apply_runtime_locale_to_invoice_template
    original_blocks = [
        {"type": "heading",
         "props": {"text": "Welcome!"}},
        {"type": "button",
         "props": {"label": "Open your portal"}},
    ]
    tpl = _tpl("system.welcome_new_customer", original_blocks)
    customer = {"id": "c1", "locale": "es"}
    tenant = {"id": "t1"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.welcome_new_customer", customer, tenant,
    )
    # Same object (or identical content) — no swap should have occurred.
    assert _find_button_label(out["blocks_json"]) == "Open your portal"


def test_runtime_locale_swap_ignores_tenant_custom_copies():
    """When a tenant duplicated ``system.invoice_created`` into their
    own custom template (``is_system=False``), the admin owns the
    copy — we must NOT overwrite it at send time."""
    from routers.comms import _apply_runtime_locale_to_invoice_template
    custom_blocks = [
        {"type": "heading", "props": {"text": "Our custom subject"}},
        {"type": "button", "props": {"label": "Pay in our style"}},
    ]
    tpl = _tpl("system.invoice_created", custom_blocks, is_system=False)
    tpl["tenant_id"] = "t1"
    customer = {"id": "c1", "locale": "es"}
    tenant = {"id": "t1", "default_locale": "es"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_created", customer, tenant,
    )
    assert _find_button_label(out["blocks_json"]) == "Pay in our style"


def test_runtime_locale_swap_preserves_all_other_template_fields():
    """Only ``blocks_json`` is swapped — subject/tenant_id/is_system/
    version/timestamps/etc. survive byte-identical so the send-path
    template row shape stays consistent."""
    from routers.comms import _apply_runtime_locale_to_invoice_template
    tpl = _tpl("system.invoice_overdue", _english_invoice_overdue_blocks())
    tpl["subject"] = "Reminder: invoice past due"
    tpl["version"] = 4
    tpl["created_at"] = "2026-01-03T00:00:00Z"
    customer = {"id": "c1", "locale": "fr"}
    tenant = {"id": "t1"}
    out = _apply_runtime_locale_to_invoice_template(
        tpl, "system.invoice_overdue", customer, tenant,
    )
    assert out["subject"] == "Reminder: invoice past due"
    assert out["version"] == 4
    assert out["created_at"] == "2026-01-03T00:00:00Z"
    assert out["code"] == "system.invoice_overdue"


# ═══════════════════════════════════════════════════════════════════
# 2 · Full deliver_one_by_ids path — captured send HTML per locale
# ═══════════════════════════════════════════════════════════════════
# Stubs: enough of the Motor surface + external adapters that
# ``deliver_one_by_ids`` can execute against an in-memory tenant +
# customer + template + template registry.


class _Coll:
    def __init__(self, rows):
        self.rows = list(rows)
        self.updates = []
        self.inserts = []

    async def find_one(self, query=None, projection=None):
        query = query or {}
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()
                    if not isinstance(v, dict)):
                return r
        return None

    async def insert_one(self, doc):
        self.inserts.append(doc)


class _FanoutColl(_Coll):
    async def find_one(self, query=None, projection=None):
        query = query or {}
        # comms.py uses ``$or`` for template lookup — handle it.
        or_clauses = query.pop("$or", None)
        for r in self.rows:
            if any(all(r.get(k) == v for k, v in c.items())
                    for c in (or_clauses or [{}])):
                if all(r.get(k) == v for k, v in query.items()
                        if not isinstance(v, dict)):
                    return r
        return await super().find_one(query, projection)


class _StubDB:
    def __init__(self, *, tenant, customer, email_template):
        self.tenants = _Coll([tenant])
        self.customers = _Coll([customer])
        self.email_templates = _FanoutColl([email_template])
        self.communication_sends = _Coll([])


async def _capture_send_html(*, tenant_default_locale: str,
                              customer_locale: str,
                              template_code: str) -> str:
    """Drive ``deliver_one_by_ids`` end-to-end with stubs; return the
    captured ``rendered_body`` HTML from the communication_sends row.
    """
    tenant = {
        "id": "t1", "name": "Acme Pool Care",
        "default_locale": tenant_default_locale,
        "portal_link": "https://acme.example",
        "phone": "+1-000-000-0000", "email": "hi@acme.example",
    }
    customer = {"id": "c1", "tenant_id": "t1",
                "email": "cust@example.com",
                "locale": customer_locale, "first_name": "Sam",
                "last_name": "River", "automations_muted": False}
    blocks = (_english_invoice_created_blocks()
              if template_code == "system.invoice_created"
              else _english_invoice_overdue_blocks())
    template = {
        "code": template_code, "tenant_id": None, "is_system": True,
        "subject": "Invoice update", "blocks_json": blocks,
    }
    stub = _StubDB(tenant=tenant, customer=customer, email_template=template)

    async def _fake_send_email(tid, contact, subject, html, from_name=None):
        return {"status": "sent", "provider_id": "px-1", "error": None}

    from routers import comms as comms_mod
    with patch.object(comms_mod, "db", stub), \
         patch.object(comms_mod, "send_email", _fake_send_email), \
         patch.object(comms_mod, "send_sms",
                       lambda *a, **k: {"status": "sent"}):
        # Force the multi-contact helper to return a single email so
        # we get one send doc back. The helper reads customer email
        # directly, so the stubbed customer suffices.
        from services import customer_multi_contact as _mc
        with patch.object(_mc, "active_email_recipients",
                            lambda cust, context="automation": [cust.get("email")]):
            await comms_mod.deliver_one_by_ids(
                tenant_id="t1",
                template_code=template_code,
                channel="email",
                recipient_id="c1",
                extras={"invoice": {"invoice_number": "INV-42",
                                     "amount_due": "$250",
                                     "due_date": "2026-02-15"}},
                automation_code="test_rule",
            )
    # Grab the captured HTML from the last insert.
    assert stub.communication_sends.inserts, "no send row captured"
    return stub.communication_sends.inserts[-1]["rendered_body"]


def test_deliver_invoice_created_english_captures_view_invoice_label():
    html = _run(_capture_send_html(
        tenant_default_locale="en",
        customer_locale="en",
        template_code="system.invoice_created",
    ))
    assert "View Invoice" in html
    assert "Ver factura" not in html
    assert "Voir la facture" not in html


def test_deliver_invoice_created_spanish_captures_ver_factura_label():
    html = _run(_capture_send_html(
        tenant_default_locale="en",
        customer_locale="es",
        template_code="system.invoice_created",
    ))
    assert "Ver factura" in html
    assert "View Invoice" not in html


def test_deliver_invoice_created_french_captures_voir_la_facture_label():
    html = _run(_capture_send_html(
        tenant_default_locale="en",
        customer_locale="fr",
        template_code="system.invoice_created",
    ))
    assert "Voir la facture" in html
    assert "View Invoice" not in html


def test_deliver_invoice_overdue_english_captures_view_invoice_label():
    html = _run(_capture_send_html(
        tenant_default_locale="en",
        customer_locale="en",
        template_code="system.invoice_overdue",
    ))
    assert "View Invoice" in html


def test_deliver_invoice_overdue_spanish_captures_ver_factura_label():
    html = _run(_capture_send_html(
        tenant_default_locale="en",
        customer_locale="es",
        template_code="system.invoice_overdue",
    ))
    assert "Ver factura" in html


def test_deliver_invoice_overdue_french_captures_voir_la_facture_label():
    html = _run(_capture_send_html(
        tenant_default_locale="en",
        customer_locale="fr",
        template_code="system.invoice_overdue",
    ))
    assert "Voir la facture" in html


def test_deliver_invoice_created_falls_back_to_tenant_locale_when_customer_missing():
    """Customer has no ``locale`` set → resolver hops to the tenant's
    ``default_locale``. This is the customer-mostly-English tenant
    with a French-preferred customer whose locale wasn't captured
    yet — they still see French because the tenant's default is FR."""
    html = _run(_capture_send_html(
        tenant_default_locale="fr",
        customer_locale="",  # simulates missing locale on customer
        template_code="system.invoice_created",
    ))
    assert "Voir la facture" in html
