"""Phase G3b Batch D · Feb 2026 — F3-integrity → BG state transitions.

The Phase F3 boot-integrity check now runs off the sync boot path
(``asyncio.create_task`` post-bind). The Phase F4 readiness gate
(``/health/ready``) must therefore transition through these states:

  1. ``boot_integrity_pending`` — set on process start, before the BG
     task runs. Readiness returns 503 ``check=integrity,
     reason=boot_integrity_pending``.
  2. ``ok`` — set when the scan completes with 0 refs. Readiness
     returns 200.
  3. ``dangling_refs_present`` — set when the scan finds refs AND
     ``INTEGRITY_CHECK_ENFORCE=true``. Readiness returns 503
     ``check=integrity, reason=dangling_refs_present,
     dangling_refs_total=<n>``.  **The BG task no longer raises to
     abort boot — it state-stamps and returns.** This is the core
     invariant Phase G3b protects.
  4. ``scan_error`` — set when the scan itself crashed (import
     error, unexpected shape, etc.). Readiness returns 503
     ``check=integrity, reason=scan_error, error=<message>``.
  5. Throughout every above state, ``/health/live`` MUST remain 200
     (k8s liveness must NOT restart the pod during any of these).

This test suite locks the state-machine directly by driving the
``_F4_BOOT_INTEGRITY_STATE`` dict inside ``server.py`` and invoking
the readiness / liveness handlers via ``fastapi.testclient``. No
Mongo scan is performed — we mock the state.
"""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _readiness_env(monkeypatch):
    # Force enforce=True + readiness gate enforce=True so the
    # ``dangling_refs_present`` branch fires deterministically.
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")
    monkeypatch.setenv("HEALTH_READY_INTEGRITY_CHECK", "true")


@pytest.fixture
def client(monkeypatch):
    # Import inside fixture so autouse env fixture applies first.
    import server as srv
    # Snapshot + restore state between tests.
    orig = dict(srv._F4_BOOT_INTEGRITY_STATE)
    yield TestClient(srv.app), srv
    srv._F4_BOOT_INTEGRITY_STATE.clear()
    srv._F4_BOOT_INTEGRITY_STATE.update(orig)


def _set_state(srv, *, complete, dangling=None, error=None):
    srv._F4_BOOT_INTEGRITY_STATE["complete"] = complete
    srv._F4_BOOT_INTEGRITY_STATE["dangling_refs_total"] = dangling
    srv._F4_BOOT_INTEGRITY_STATE["error"] = error


# ═══════════════════════════ State 1 · pending ═══════════════════════
def test_ready_pending_returns_503_and_live_stays_200(client):
    tc, srv = client
    _set_state(srv, complete=False, dangling=None, error=None)

    r = tc.get("/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "not_ready"
    checks = body["checks"]
    assert checks["integrity"] == "pending"
    assert any(
        (f.get("check") == "integrity"
            and f.get("reason") == "boot_integrity_pending")
        for f in (body.get("failures") or [])
    ), body

    live = tc.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"


# ═══════════════════════════ State 2 · ok ═══════════════════════════
def test_ready_ok_when_clean_scan(client):
    tc, srv = client
    _set_state(srv, complete=True, dangling=0, error=None)

    r = tc.get("/health/ready")
    # Mongo + migrations checks may still fail against the test DB;
    # what we're locking is that the integrity check itself is ``ok``.
    body = r.json()
    assert body["checks"]["integrity"] == "ok", body
    if r.status_code == 200:
        assert body["status"] == "ready"

    live = tc.get("/health/live")
    assert live.status_code == 200


# ═══════════════════════════ State 3 · dangling_refs_present ══════════
def test_ready_dangling_refs_present_returns_503_no_boot_abort(client):
    """The critical G3b Batch D invariant: with enforce=True and
    refs>0, the BG task state-stamps + returns instead of raising.
    /health/ready reports the correct reason + count."""
    tc, srv = client
    _set_state(srv, complete=True, dangling=42, error=None)

    r = tc.get("/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["integrity"] == "fail"

    integ_fails = [f for f in (body.get("failures") or [])
                    if f.get("check") == "integrity"]
    assert integ_fails, body
    assert integ_fails[0].get("reason") == "dangling_refs_present"
    assert integ_fails[0].get("dangling_refs_total") == 42

    # dangling_refs_total mirrored at top level of payload.
    assert body.get("dangling_refs_total") == 42

    # Liveness must NOT flip.
    live = tc.get("/health/live")
    assert live.status_code == 200


# ═══════════════════════════ State 4 · scan_error ════════════════════
def test_ready_scan_error_returns_503(client):
    tc, srv = client
    _set_state(srv, complete=True, dangling=None,
                error="import: no module named blah")

    r = tc.get("/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["checks"]["integrity"] == "fail"
    integ_fails = [f for f in (body.get("failures") or [])
                    if f.get("check") == "integrity"]
    assert integ_fails, body
    assert integ_fails[0].get("reason") == "scan_error"
    assert integ_fails[0].get("error", "").startswith("import:")

    live = tc.get("/health/live")
    assert live.status_code == 200


# ═══════════════════════════ Regression: no-raise boot semantics ══════
def test_startup_no_longer_raises_on_enforce_dangling_refs():
    """G3b Batch D: the ``startup()`` handler must not contain the
    ``raise IntegrityCheckFailure`` control flow that historically
    aborted boot on enforce=True + refs>0.

    We assert the source itself — this is the invariant that keeps
    prod pods alive-but-503 instead of crash-looping.
    """
    server_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "server.py",
    )
    with open(server_path, "r", encoding="utf-8") as fh:
        src = fh.read()

    # The retired sync-path handler included the line ``raise`` at
    # module scope inside the ``if isinstance(exc, IntegrityCheckFailure):``
    # branch. G3b Batch D removes it — no bare ``raise`` may exist
    # anywhere in the F3 integrity handling block.
    #
    # We anchor on the batch-D marker so this check stays targeted.
    assert "G3b Batch D · Feb-2026 — moved to BG" in src, \
        "Batch D marker missing — has the F3 refactor been reverted?"

    # Locate the BG closure and assert no ``raise`` inside it.
    marker = "async def _bg_f3_integrity_check():"
    idx = src.find(marker)
    assert idx > 0, "BG closure for F3 integrity check not found in server.py"
    end_idx = src.find(
        "asyncio.create_task(_bg_f3_integrity_check())", idx,
    )
    assert end_idx > idx, "BG closure body has no scheduling call"
    body = src[idx:end_idx]
    # ``raise`` must not appear as a control-flow statement inside
    # the closure body. (We tolerate the word inside a comment or
    # docstring, but the file scan will surface any real occurrence.)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("raise"), (
            f"G3b Batch D violation — bare ``raise`` inside F3 BG closure:"
            f" {line!r}"
        )
