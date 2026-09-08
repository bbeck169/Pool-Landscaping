"""P0 · Feb-2026 — Comms whitelist banner truth-source.

Regression guard for the "prod comms-gate banner stuck ON" hotfix.

The Settings → Notifications red banner
("Outbound communications are gated (demo-only mode).") is driven
by ``GET /api/comms/whitelist/status`` → response field
``whitelist_active``. Previously the endpoint hardcoded
``whitelist_active: True``, which meant:

* Preview / staging: correct — banner lit up, gate active.
* **Production: INCORRECT** — banner lit up even though the
  underlying ``services.comms.gate.is_comm_allowed`` returned
  ``True`` (real customer comms were flowing correctly). Ops read
  the banner, thought real customers were being suppressed.

The fix wires ``whitelist_active`` to
``services.comms.gate.current_gate_policy()`` so the banner
reflects the *actual* gate — same truth-source the real outbound
chokepoint consults.

Invariants asserted:
  1. Endpoint continues to require an authed admin session.
  2. Live-preview pod (``APP_ENV=preview``) → banner stays up +
     ``gate_policy="demo_only"``.
  3. ``current_gate_policy()`` flips to ``"prod_bypass"`` when
     ``APP_ENV=production`` is set in-process.
  4. ``_app_env()`` defaults to ``"preview"`` (fail-safe) when the
     env var is missing.
  5. Source-level: the router function actually reads through
     ``current_gate_policy`` — a regression that reintroduces the
     hardcoded ``True`` would fail here.

Env-flip branches are unit-tested in-process because mutating
``os.environ`` from the pytest process does NOT reach the running
uvicorn server — the pod-level ``APP_ENV`` is loaded at start-up.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"


def _login(email: str = "super@aquaterra.com",
             password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def _env_restore():
    prev = os.environ.get("APP_ENV")
    yield
    if prev is None:
        os.environ.pop("APP_ENV", None)
    else:
        os.environ["APP_ENV"] = prev


# ─────────────────────────────────────────────────────────────────
# 1. Auth is still required — the endpoint is admin-only.
# ─────────────────────────────────────────────────────────────────
def test_comms_whitelist_status_requires_authed_session():
    """Anon GET MUST NOT leak gate policy / counts. The banner is
    only meant for logged-in admins on ``/settings/notifications``.
    """
    r = requests.get(f"{API}/comms/whitelist/status", timeout=15)
    assert r.status_code in (401, 403), (
        f"Anon GET returned {r.status_code} — endpoint is admin-only. "
        f"Body head: {r.text[:200]!r}"
    )


# ─────────────────────────────────────────────────────────────────
# 2. Preview-pod live check: banner up, policy=demo_only.
#     Pod's ``APP_ENV=preview`` (see backend/.env) so this exercises
#     the real handler end-to-end against the running server.
# ─────────────────────────────────────────────────────────────────
def test_comms_whitelist_status_live_preview_keeps_banner_up():
    """Preview pod (``APP_ENV=preview``) MUST show the red banner
    (``whitelist_active=True``, ``gate_policy="demo_only"``).
    Losing this would let a preview pod silently dispatch real
    customer emails on the next Resend call.
    """
    tok = _login()
    r = requests.get(f"{API}/comms/whitelist/status",
                       headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["whitelist_active"] is True, (
        "Preview pod but whitelist_active is False. Preview safety "
        f"banner would go missing. Response: {body!r}"
    )
    assert body["gate_policy"] == "demo_only", (
        f"Expected gate_policy='demo_only' on preview pod; "
        f"got {body.get('gate_policy')!r}"
    )
    assert body["app_env"] == "preview", (
        f"Expected app_env='preview' on preview pod; "
        f"got {body.get('app_env')!r}"
    )
    # Counters must still ship with the response for the FE tile.
    for k in ("users_flagged_demo", "customers_flagged_demo",
              "suppressed_last_24h"):
        assert k in body and isinstance(body[k], int), (
            f"Missing/typed-wrong counter '{k}' in response: {body!r}"
        )


# ─────────────────────────────────────────────────────────────────
# 3. In-process env flip → policy=prod_bypass.
#     The router body imports ``current_gate_policy`` on every
#     request, so an in-process ``os.environ`` flip on this side of
#     the pytest wire is sufficient to prove the branch. Live-HTTP
#     verification of prod behaviour requires the deployment env
#     itself to have ``APP_ENV=production`` — that's ops' job.
# ─────────────────────────────────────────────────────────────────
def test_current_gate_policy_flips_to_prod_bypass_when_app_env_is_production(_env_restore):
    """``current_gate_policy()`` MUST return ``"prod_bypass"`` when
    ``APP_ENV=production``. This is the exact function the fixed
    banner endpoint calls, so proving it here proves the fix — a
    prod pod with ``APP_ENV=production`` will report
    ``whitelist_active=False``.
    """
    from services.comms.gate import current_gate_policy

    os.environ["APP_ENV"] = "production"
    assert current_gate_policy() == "prod_bypass", (
        "current_gate_policy() did not return 'prod_bypass' with "
        "APP_ENV=production. The banner endpoint would light up on "
        "prod even after this hotfix."
    )

    os.environ["APP_ENV"] = "preview"
    assert current_gate_policy() == "demo_only", (
        "current_gate_policy() did not return 'demo_only' with "
        "APP_ENV=preview. Preview safety would be lost."
    )


# ─────────────────────────────────────────────────────────────────
# 4. Default-unset fails safe.
# ─────────────────────────────────────────────────────────────────
def test_app_env_defaults_to_preview_when_unset(_env_restore):
    """A fresh pod with ``APP_ENV`` missing MUST default to preview
    (banner ON). Inverting the default would let a first-boot pod
    silently dispatch real customer comms.
    """
    from services.comms_env_guard import _app_env, is_production
    from services.comms.gate import current_gate_policy

    os.environ.pop("APP_ENV", None)
    assert _app_env() == "preview"
    assert is_production() is False
    assert current_gate_policy() == "demo_only"


# ─────────────────────────────────────────────────────────────────
# 5. Source-level: banner endpoint wires the policy in.
#     A regression that reintroduces ``"whitelist_active": True``
#     hardcoded (the original bug) would fail here.
# ─────────────────────────────────────────────────────────────────
def test_whitelist_status_source_reads_current_gate_policy():
    src = Path(__file__).resolve().parents[1] / "routers" / "comms_admin.py"
    text = src.read_text()

    fn = text.split("async def whitelist_status(")[1].split("\nasync def ")[0]

    assert "current_gate_policy" in fn, (
        "whitelist_status no longer imports/calls current_gate_policy. "
        "The banner is likely back to a hardcoded True — regression."
    )
    assert 'policy != "prod_bypass"' in fn or "prod_bypass" in fn, (
        "whitelist_status body no longer branches on 'prod_bypass'. "
        "The banner truth-source has drifted from the outbound gate."
    )
    # Guard against the exact regression: hardcoded ``True`` literal
    # on the ``whitelist_active`` key.
    assert '"whitelist_active": True' not in fn, (
        "whitelist_status has reintroduced the hardcoded "
        "``\"whitelist_active\": True`` literal — this is the "
        "original P0 bug. Wire it back to current_gate_policy()."
    )
