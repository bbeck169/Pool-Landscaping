"""Feb-2026 · Stripe webhook Thin-payload compat — pytest.

Stripe Workbench Event Destinations default new destinations to the
"Thin" payload style, which the SDK's ``Webhook.construct_event``
explicitly rejects with a ``ValueError`` containing "thin event
notification". This test suite locks in the fallback path added to
``backend/services/payments/stripe_charge.py::verify_and_parse_webhook``:

  1. Snapshot payload (legacy destination or explicit Snapshot Event
     Destination) → classic path, no ``Event.retrieve`` call.
  2. Thin payload → detect the "thin event notification" error,
     manually verify the signature via
     ``stripe.WebhookSignature.verify_header``, JSON-parse the envelope,
     call ``stripe.Event.retrieve`` to hydrate the full Snapshot event,
     dispatch downstream unchanged.
  3. Bad signature → still 400 (SDK's ``SignatureVerificationError``).
  4. Thin payload + ``Event.retrieve`` transient failure → raise
     ``ThinPayloadRetrieveError`` (router maps to 502 so Stripe retries).
  5. Idempotency preserved — feeding the same hydrated event twice
     causes a single ``stripe_charges`` row (upsert-by-PI dedupe).

The unit tests monkey-patch ``stripe.Webhook.construct_event``,
``stripe.WebhookSignature.verify_header``, and ``stripe.Event.retrieve``
so we exercise the fallback branches without a live Stripe call.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dotenv import dotenv_values

# NOTE — this test file does NOT create a module-level event loop or
# set it as the current loop. That pattern (used elsewhere in the
# suite) contaminates ``motor``'s bound loop for any test that runs
# after this one in the same pytest session. See the Feb-2026 batch
# regression triage where the classic pattern turned
# ``test_stripe_reconciliation.py`` into 14 errors when co-run.
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


# Suffix every test-created id so cleanup is precise + tests are re-runnable.
PREFIX = f"twthin-{uuid.uuid4().hex[:8]}"


# Minimal Snapshot payment_intent.succeeded body — used to build the
# "hydrated" event that Event.retrieve returns during the thin path,
# AND directly as the classic-path input.
def _snapshot_pi_succeeded(evt_id: str, pi_id: str) -> dict:
    return {
        "id": evt_id,
        "object": "event",
        "type": "payment_intent.succeeded",
        "api_version": "2024-06-20",
        "data": {
            "object": {
                "id": pi_id,
                "object": "payment_intent",
                "amount": 12345,
                "amount_received": 12345,
                "currency": "usd",
                "payment_method": None,
                "metadata": {},   # no crm_* → invoice update skipped
                "last_payment_error": None,
                "status": "succeeded",
            },
        },
    }


def _thin_pi_succeeded(evt_id: str) -> dict:
    """Stripe's Thin envelope — no ``data.object``, only pointers."""
    return {
        "id": evt_id,
        "object": "v2.core.event",
        "type": "payment_intent.succeeded",
        "api_version": "2024-06-20",
        "related_object": {"id": f"pi_{uuid.uuid4().hex[:12]}",
                            "type": "payment_intent"},
    }


# ═══════════════════════════════════════════════════════════════════
# 1 · Snapshot payload — classic path, retrieve NOT called.
# ═══════════════════════════════════════════════════════════════════
def test_snapshot_payload_uses_classic_path_no_retrieve(monkeypatch):
    from services.payments import stripe_charge as sc

    evt_id = f"evt_{PREFIX}_snap"
    pi_id = f"pi_{PREFIX}_snap"
    body = _snapshot_pi_succeeded(evt_id, pi_id)

    # ``construct_event`` succeeds → we never hit the fallback path.
    def fake_construct(payload, sig, secret, tolerance=300, api_key=None):
        assert secret, "secret must be present"
        return body
    monkeypatch.setattr(
        sc._stripe.Webhook, "construct_event", fake_construct,
    )

    # If the code takes the fallback branch, this must NOT be called.
    retrieve_calls = {"n": 0}

    def fake_retrieve(evt_id_arg, **kwargs):
        retrieve_calls["n"] += 1
        return body
    monkeypatch.setattr(sc._stripe.Event, "retrieve", fake_retrieve)

    # Force a secret so the early-return doesn't fire.
    monkeypatch.setattr(sc, "_select_webhook_secret", lambda: "whsec_test")

    event = sc.verify_and_parse_webhook(
        payload=json.dumps(body).encode(),
        sig_header="t=123,v1=deadbeef",
    )
    assert event["type"] == "payment_intent.succeeded"
    assert event["data"]["object"]["id"] == pi_id
    assert retrieve_calls["n"] == 0, "classic path must not call Event.retrieve"


# ═══════════════════════════════════════════════════════════════════
# 2 · Thin payload — hydrates via manual verify + Event.retrieve.
# ═══════════════════════════════════════════════════════════════════
def test_thin_payload_hydrates_via_event_retrieve(monkeypatch):
    from services.payments import stripe_charge as sc

    evt_id = f"evt_{PREFIX}_thin"
    pi_id = f"pi_{PREFIX}_thin"
    thin_body = _thin_pi_succeeded(evt_id)
    snapshot_body = _snapshot_pi_succeeded(evt_id, pi_id)

    # 2a · ``construct_event`` raises the exact Thin rejection.
    def fake_construct(payload, sig, secret, tolerance=300, api_key=None):
        raise ValueError(
            "You passed a thin event notification to Webhook.construct_event, "
            "which expects a webhook payload.",
        )
    monkeypatch.setattr(
        sc._stripe.Webhook, "construct_event", fake_construct,
    )

    # 2b · Manual signature verify must be called with the same args.
    verify_calls = {"n": 0}

    def fake_verify(payload, sig, secret, tolerance=None):
        verify_calls["n"] += 1
        assert secret == "whsec_test"
        # Emulate the SDK — no return value on success, raises on bad sig.
    monkeypatch.setattr(
        sc._stripe.WebhookSignature, "verify_header", fake_verify,
    )

    # 2c · ``Event.retrieve`` returns the full Snapshot event.
    retrieve_calls = {"n": 0, "id": None}

    def fake_retrieve(evt_id_arg, **kwargs):
        retrieve_calls["n"] += 1
        retrieve_calls["id"] = evt_id_arg
        return snapshot_body
    monkeypatch.setattr(sc._stripe.Event, "retrieve", fake_retrieve)

    monkeypatch.setattr(sc, "_select_webhook_secret", lambda: "whsec_test")

    event = sc.verify_and_parse_webhook(
        payload=json.dumps(thin_body).encode(),
        sig_header="t=123,v1=deadbeef",
    )
    # The hydrated event must be the FULL Snapshot shape — downstream
    # handlers see ``data.object`` populated exactly as before.
    assert event["type"] == "payment_intent.succeeded"
    assert event["data"]["object"]["id"] == pi_id
    assert event["data"]["object"]["amount"] == 12345
    # Assertions on the fallback branch mechanics.
    assert verify_calls["n"] == 1, "manual signature verify must be called once"
    assert retrieve_calls["n"] == 1, "Event.retrieve must be called once"
    assert retrieve_calls["id"] == evt_id, \
        "Event.retrieve must be called with the envelope's event id"


# ═══════════════════════════════════════════════════════════════════
# 3 · Bad signature — non-thin error must NOT trigger fallback.
# ═══════════════════════════════════════════════════════════════════
def test_bad_signature_still_rejected(monkeypatch):
    from services.payments import stripe_charge as sc

    # Emulate the SDK's SignatureVerificationError. We don't want to
    # import the concrete class since it moved between SDK versions
    # (``stripe.error.SignatureVerificationError`` → ``stripe.SignatureVerificationError``),
    # so we build a lookalike ``Exception`` — the handler catches
    # broadly and matches on message content.
    class FakeSigErr(Exception):
        pass

    def fake_construct(payload, sig, secret, tolerance=300, api_key=None):
        raise FakeSigErr("No signatures found matching the expected signature for payload.")
    monkeypatch.setattr(
        sc._stripe.Webhook, "construct_event", fake_construct,
    )

    # Guardrail — if the fallback branch is (wrongly) taken, these
    # must NOT be called. Blow up loudly if they are.
    def fail_verify(*a, **kw):
        raise AssertionError("fallback must NOT run for a signature error")
    monkeypatch.setattr(
        sc._stripe.WebhookSignature, "verify_header", fail_verify,
    )
    monkeypatch.setattr(
        sc._stripe.Event, "retrieve",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Event.retrieve must not fire on bad sig")),
    )
    monkeypatch.setattr(sc, "_select_webhook_secret", lambda: "whsec_test")

    with pytest.raises(FakeSigErr):
        sc.verify_and_parse_webhook(
            payload=b'{"id":"evt_x"}',
            sig_header="t=123,v1=bad",
        )


# ═══════════════════════════════════════════════════════════════════
# 4 · Thin path + Event.retrieve transient failure → ThinPayloadRetrieveError.
# ═══════════════════════════════════════════════════════════════════
def test_thin_payload_retrieve_failure_raises_transient_error(monkeypatch):
    from services.payments import stripe_charge as sc

    thin_body = _thin_pi_succeeded(f"evt_{PREFIX}_fail")

    monkeypatch.setattr(
        sc._stripe.Webhook, "construct_event",
        lambda p, s, sec, tolerance=300, api_key=None: (_ for _ in ()).throw(
            ValueError("You passed a thin event notification to Webhook.construct_event."),
        ),
    )
    monkeypatch.setattr(
        sc._stripe.WebhookSignature, "verify_header",
        lambda p, s, sec, tolerance=None: None,
    )

    class TransientStripeErr(Exception):
        pass

    monkeypatch.setattr(
        sc._stripe.Event, "retrieve",
        lambda evt_id, **kwargs: (_ for _ in ()).throw(
            TransientStripeErr("upstream 503"),
        ),
    )
    monkeypatch.setattr(sc, "_select_webhook_secret", lambda: "whsec_test")

    with pytest.raises(sc.ThinPayloadRetrieveError) as exc_info:
        sc.verify_and_parse_webhook(
            payload=json.dumps(thin_body).encode(),
            sig_header="t=123,v1=deadbeef",
        )
    # Error message carries the underlying reason + the event id so
    # the ops person reading logs can find the row.
    assert "upstream 503" in str(exc_info.value)
    assert PREFIX in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════
# 5 · Idempotency — same hydrated event fed twice → the upsert-by-PI
#      code path fires with the SAME predicate both times, which is
#      what makes Mongo's ``upsert=True`` a no-op on the second write.
#      We assert this at the code-path level (fake ``db`` object, no
#      motor coupling) to avoid any event-loop hazard; the actual
#      Mongo dedup behavior is separately locked in by
#      ``test_stripe_reconciliation.py``.
# ═══════════════════════════════════════════════════════════════════
class _FakeCollection:
    """Lightweight stand-in for a motor collection — just records
    every ``update_one`` call so tests can assert on the predicate.
    No event-loop coupling."""
    def __init__(self):
        self.update_one_calls: list = []

    async def update_one(self, filter_, update, upsert=False):
        self.update_one_calls.append({"filter": filter_, "update": update,
                                        "upsert": upsert})
        return MagicMock(matched_count=1, modified_count=1, upserted_id=None)


class _FakeDB:
    def __init__(self):
        self.stripe_charges = _FakeCollection()


def test_thin_payload_idempotent_double_delivery(monkeypatch):
    from services.payments import stripe_charge as sc

    evt_id = f"evt_{PREFIX}_idem"
    pi_id = f"pi_{PREFIX}_idem"
    snap = _snapshot_pi_succeeded(evt_id, pi_id)

    # Force the fallback path both times so we exercise it end-to-end
    # (real-world: every delivery from the Thin destination arrives thin).
    monkeypatch.setattr(
        sc._stripe.Webhook, "construct_event",
        lambda p, s, sec, tolerance=300, api_key=None: (_ for _ in ()).throw(
            ValueError("You passed a thin event notification to Webhook.construct_event."),
        ),
    )
    monkeypatch.setattr(
        sc._stripe.WebhookSignature, "verify_header",
        lambda p, s, sec, tolerance=None: None,
    )
    monkeypatch.setattr(
        sc._stripe.Event, "retrieve",
        lambda evt_id_arg, **kwargs: snap,
    )
    monkeypatch.setattr(sc, "_select_webhook_secret", lambda: "whsec_test")

    # Replace the motor ``db`` in stripe_charge's namespace with a
    # fake — the only motor call ``handle_webhook_event`` makes on
    # the ``payment_intent.succeeded`` branch (skip-invoice sub-branch,
    # since our snapshot has empty metadata) lands on the fake, which
    # records calls without any motor / event-loop interaction.
    fake_db = _FakeDB()
    monkeypatch.setattr(sc, "db", fake_db)

    # Isolated loop — never leaks into the pytest session loop, so
    # motor-backed tests in OTHER files stay pristine when co-run.
    loop = asyncio.new_event_loop()
    try:
        event1 = sc.verify_and_parse_webhook(
            payload=json.dumps(_thin_pi_succeeded(evt_id)).encode(),
            sig_header="t=1,v1=x",
        )
        r1 = loop.run_until_complete(sc.handle_webhook_event(event1))

        # Second delivery — Stripe replays the same event id.
        event2 = sc.verify_and_parse_webhook(
            payload=json.dumps(_thin_pi_succeeded(evt_id)).encode(),
            sig_header="t=2,v1=x",
        )
        r2 = loop.run_until_complete(sc.handle_webhook_event(event2))
    finally:
        loop.close()

    # Both deliveries handled the event successfully.
    assert r1["handled"] is True
    assert r2["handled"] is True
    # And both hit the SAME upsert predicate — that's the property Mongo
    # relies on to make the second write a no-op. Filter must be keyed
    # on the payment_intent id + the $set must carry the same terminal
    # status.
    calls = fake_db.stripe_charges.update_one_calls
    assert len(calls) == 2, (
        f"expected 2 update_one calls (one per delivery), got {len(calls)}"
    )
    for call in calls:
        assert call["filter"] == {"stripe_payment_intent_id": pi_id}
        assert call["upsert"] is True
        assert call["update"]["$set"]["status"] == "succeeded"
        assert call["update"]["$set"]["stripe_payment_intent_id"] == pi_id
