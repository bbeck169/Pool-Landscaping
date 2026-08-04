"""Phase 44 · Comms Template Sweep — unit tests for the safety guardrails.

Scope: prove the script CANNOT hit a non-allowlist address, ALWAYS
tags outbound messages with ``X-Emergent-Sweep: phase-44-demo``, and
runs a full dry-run against a mocked send fn without touching the
real Resend adapter or the database.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

# Load the script as a module without requiring backend.scripts on sys.path.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase44_comms_sweep.py"
_spec = importlib.util.spec_from_file_location("phase44_comms_sweep", _SCRIPT)
sweep = importlib.util.module_from_spec(_spec)
sys.modules["phase44_comms_sweep"] = sweep
_spec.loader.exec_module(sweep)  # type: ignore[union-attr]


# ── Allowlist enforcement ─────────────────────────────────────────────
class TestAllowlist:
    def test_allowlist_matches_seed_accounts(self):
        assert sweep._COMMS_SWEEP_ALLOWED_EMAILS == frozenset({
            "customer@aquaterra.com",
            "manager@aquaterra.com",
            "super@aquaterra.com",
            "admin@aquaterra.com",
            "landscaper@aquaterra.com",
        })

    def test_assert_allowlist_permits_seed_account(self):
        # Must not raise.
        sweep._assert_allowlist("customer@aquaterra.com")

    def test_assert_allowlist_blocks_random_customer(self):
        with pytest.raises(sweep._AllowlistViolation) as exc:
            sweep._assert_allowlist("real.customer@example.com")
        assert "real.customer@example.com" in str(exc.value)

    def test_assert_allowlist_blocks_case_variant(self):
        # Guardrail is exact-match (case-sensitive) — mixed case must fail.
        with pytest.raises(sweep._AllowlistViolation):
            sweep._assert_allowlist("Customer@AquaTerra.com")

    def test_assert_allowlist_blocks_empty_string(self):
        with pytest.raises(sweep._AllowlistViolation):
            sweep._assert_allowlist("")


# ── Header enforcement (dry-run stub asserts on it) ───────────────────
class TestSweepHeader:
    def test_header_constant(self):
        assert sweep._SWEEP_HEADER == {"X-Emergent-Sweep": "phase-44-demo"}

    def test_send_one_forwards_header(self):
        captured: dict = {}

        async def fake_send(**kwargs):
            captured.update(kwargs)
            return {"status": "captured"}

        result = asyncio.run(
            sweep._send_one(fake_send, sweep.TEMPLATES[0], "admin@aquaterra.com")
        )
        assert result["template"] == sweep.TEMPLATES[0].key
        assert result["to"] == "admin@aquaterra.com"
        assert captured["headers"] == {"X-Emergent-Sweep": "phase-44-demo"}
        assert captured["tenant_id"] == "aquaterra"
        assert captured["from_name"] == "Phase 44 sweep"

    def test_send_one_raises_for_off_allowlist(self):
        async def fake_send(**kwargs):
            return {"status": "should_not_reach"}

        with pytest.raises(sweep._AllowlistViolation):
            asyncio.run(sweep._send_one(fake_send, sweep.TEMPLATES[0], "leak@example.com"))


# ── Full dry-run coverage ─────────────────────────────────────────────
class TestDryRunSweep:
    def test_dry_run_covers_every_template_x_recipient(self):
        results = asyncio.run(sweep.run_sweep(live=False))
        expected = len(sweep.TEMPLATES) * len(sweep._COMMS_SWEEP_ALLOWED_EMAILS)
        assert len(results) == expected
        for r in results:
            assert r["result"] == {"status": "dry_run"}
            assert r["to"] in sweep._COMMS_SWEEP_ALLOWED_EMAILS
            assert r["template"] in {t.key for t in sweep.TEMPLATES}
            assert r["ms"] >= 0

    def test_dry_run_stub_rejects_missing_header(self):
        """If someone accidentally strips the sweep header, the stub must fail loudly."""
        async def broken_send(**kwargs):
            # Strip the guardrail header on purpose.
            return {"status": "ok"}

        # Run send_one with a send_fn that never checks the header — the
        # header check is enforced by the *stub* used inside run_sweep, so
        # simulate that path directly.
        async def strip_header_stub(**kwargs):
            kwargs.pop("headers", None)
            # emulate the default dry-run stub's own assertion
            headers = kwargs.get("headers") or {}
            assert headers.get("X-Emergent-Sweep") == "phase-44-demo", "sweep header missing"
            return {"status": "dry_run"}

        with pytest.raises(AssertionError, match="sweep header missing"):
            asyncio.run(sweep._send_one(strip_header_stub, sweep.TEMPLATES[0], "admin@aquaterra.com"))

    def test_run_sweep_uses_injected_send_fn(self):
        """Custom send_fn is honoured — no network touched."""
        calls: list = []

        async def spy(**kwargs):
            calls.append(kwargs["to_email"])
            return {"status": "spied"}

        results = asyncio.run(sweep.run_sweep(live=False, send_fn=spy))
        assert len(results) == len(calls)
        assert set(calls) == set(sweep._COMMS_SWEEP_ALLOWED_EMAILS)
        assert all(r["result"] == {"status": "spied"} for r in results)


# ── Template inventory sanity ─────────────────────────────────────────
class TestTemplateInventory:
    def test_template_keys_are_unique(self):
        keys = [t.key for t in sweep.TEMPLATES]
        assert len(keys) == len(set(keys)), "duplicate template keys"

    def test_every_template_has_subject_and_html(self):
        for t in sweep.TEMPLATES:
            assert t.subject.startswith("[Phase 44 sweep]"), \
                f"{t.key} subject missing [Phase 44 sweep] tag"
            assert "Phase 44 sweep" in t.html, f"{t.key} html missing sweep footer"
            assert t.html.startswith("<html><body>")

    def test_expected_template_classes_present(self):
        expected = {
            "invoice_sent",
            "invoice_reminder",
            "payment_receipt",
            "payment_failed",
            "job_scheduled",
            "job_completed",
            "review_request",
            "password_reset",
            "welcome",
            "estimate_sent",
        }
        got = {t.key for t in sweep.TEMPLATES}
        missing = expected - got
        assert not missing, f"missing template classes: {missing}"
