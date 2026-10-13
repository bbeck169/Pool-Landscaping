"""WINGMAN-ESCALATION-EMAIL-FIX · Feb-2026.

Pytest for the admin-notification fan-out at
``backend/services/notifications.py::_dispatch_email``.  Validates
that the "Open" link in the rendered email body is an absolute
HTTPS URL (NOT ``file:///...``) and that misconfiguration fails
loudly via the shared ``absolute_portal_url`` helper.

Three cases:
  (i)   Rendered email contains an ``https://`` ``<a href>`` with
        the conversation-id path when ``APP_PUBLIC_URL`` is set.
  (ii)  Missing ``APP_PUBLIC_URL`` → ERROR log fires naming the
        template AND the rendered html uses the visible placeholder
        host (``https://CONFIGURATION_MISSING_APP_PUBLIC_URL``) —
        NOT ``file:///...``.
  (iii) Regression guard: raw substring ``file:///`` MUST NEVER
        appear in the rendered html for either env state.

Synthetic data only; no PII in any assertion string.
"""
from __future__ import annotations

import logging
import uuid

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _ids() -> tuple:
    tid = f"test-wingman-{uuid.uuid4()}"
    uid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    return tid, uid, cid


class _ResendCapture:
    """Replacement for ``resend.Emails`` — captures the payload the
    dispatcher tried to send and no-ops the network call."""
    captured: list = []

    @classmethod
    def send(cls, payload):
        cls.captured.append(payload)
        return {"id": "mock-email-id"}


async def _seed_user(db, tid: str, uid: str, email: str):
    await db.users.insert_one({
        "id": uid, "tenant_id": tid, "role": "admin",
        "email": email, "active": True,
    })


async def _cleanup(db, tid: str):
    await db.users.delete_many({"tenant_id": tid})
    await db.email_delivery_log.delete_many({"tenant_id": tid})


# ─── (i) + (iii) · configured base → https link + no file:/// ─────
def test_dispatch_email_renders_absolute_https_link(monkeypatch):
    tid, uid, cid = _ids()
    email = f"a-{uuid.uuid4().hex[:8]}@synthetic.test"

    async def _run(db):
        try:
            await _seed_user(db, tid, uid, email)

            # Pin the public base URL so the helper joins
            # deterministically.
            import config as cfg
            import services.email_urls as urls_mod
            monkeypatch.setattr(cfg, "APP_PUBLIC_URL", "https://app.example.test")
            monkeypatch.setattr(
                urls_mod, "APP_PUBLIC_URL", "https://app.example.test",
            )

            # Stub resend + its api key + the gate so the dispatcher
            # reaches the html-render branch deterministically.
            monkeypatch.setenv("RESEND_API_KEY", "test-key")
            monkeypatch.setenv("RESEND_FROM", "test@example.test")
            _ResendCapture.captured = []

            import resend  # type: ignore
            monkeypatch.setattr(resend, "Emails", _ResendCapture)

            import services.comms.gate as gate
            async def _allow(**_kw):
                return True
            monkeypatch.setattr(gate, "is_comm_allowed", _allow)

            from services.notifications import _dispatch_email
            await _dispatch_email(
                tenant_id=tid, user_id=uid,
                subject="A convo was escalated",
                body="Wingman escalated conversation.",
                kind="ai_escalation",
                href=f"/communication/{cid}",
            )

            assert len(_ResendCapture.captured) == 1
            html = _ResendCapture.captured[0]["html"]
            # (i) absolute HTTPS link with the conversation-id path.
            assert (
                f'href="https://app.example.test/communication/{cid}"'
                in html
            ), html
            # (iii) regression guard — no file:/// substring anywhere.
            assert "file:///" not in html
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (ii) + (iii) · missing env → ERROR log + visible placeholder ─
def test_dispatch_email_missing_env_logs_error_and_emits_placeholder(
    monkeypatch, caplog,
):
    tid, uid, cid = _ids()
    email = f"b-{uuid.uuid4().hex[:8]}@synthetic.test"

    async def _run(db):
        try:
            await _seed_user(db, tid, uid, email)

            # Simulate the broken-env state.
            import config as cfg
            import services.email_urls as urls_mod
            monkeypatch.setattr(cfg, "APP_PUBLIC_URL", "")
            monkeypatch.setattr(urls_mod, "APP_PUBLIC_URL", "")

            monkeypatch.setenv("RESEND_API_KEY", "test-key")
            monkeypatch.setenv("RESEND_FROM", "test@example.test")
            _ResendCapture.captured = []

            import resend  # type: ignore
            monkeypatch.setattr(resend, "Emails", _ResendCapture)

            import services.comms.gate as gate
            async def _allow(**_kw):
                return True
            monkeypatch.setattr(gate, "is_comm_allowed", _allow)

            from services.notifications import _dispatch_email
            with caplog.at_level(logging.ERROR):
                await _dispatch_email(
                    tenant_id=tid, user_id=uid,
                    subject="A convo was escalated",
                    body="Wingman escalated conversation.",
                    kind="ai_escalation",
                    href=f"/communication/{cid}",
                )

            # (ii) ERROR log fired AND names the template.
            err_matched = [
                r for r in caplog.records
                if r.levelno == logging.ERROR
                and "[email-urls]" in r.getMessage()
                and "admin_notification_fanout:ai_escalation"
                in r.getMessage()
            ]
            assert err_matched, (
                "expected ERROR log tagged [email-urls] with the "
                "ai_escalation template name"
            )

            # Visible placeholder host — NOT file:///.
            assert len(_ResendCapture.captured) == 1
            html = _ResendCapture.captured[0]["html"]
            assert (
                "https://CONFIGURATION_MISSING_APP_PUBLIC_URL"
                in html
            )
            # (iii) regression guard — never emit file:///.
            assert "file:///" not in html
        finally:
            await _cleanup(db, tid)

    run_test(_run)
