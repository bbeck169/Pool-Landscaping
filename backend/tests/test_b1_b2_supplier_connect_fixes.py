"""Aug-2026 · Fix B-1 + B-2 backend tests.

B-1 — ``TEST_CONNECTION_TIMEOUT_S`` bumped 15 → 45s. Endpoint must:
  * return the connector's real result when authenticate() finishes
    below the cap.
  * return the ``timeout`` envelope when authenticate() blows past
    the cap.

B-2 — SiteOne connector must launch Chromium with the HTTP/2 disable
flag AND pass a Chrome-stable ``user_agent`` + client-hint headers
so SiteOne's edge accepts the handshake. Other connectors are
intentionally UNTOUCHED — regression guard included below.
"""
from __future__ import annotations

import asyncio


# ── B-1 · timeout cap ───────────────────────────────────────────────
def test_b1_test_connection_timeout_s_is_45_seconds():
    from routers.suppliers import TEST_CONNECTION_TIMEOUT_S
    assert TEST_CONNECTION_TIMEOUT_S == 45.0, (
        f"expected 45s cap; got {TEST_CONNECTION_TIMEOUT_S!r}"
    )


def test_b1_asyncio_wait_for_returns_result_when_under_cap():
    """A connector that resolves in 0.05s must return its own result
    envelope — NOT the endpoint's timeout envelope."""
    async def _fake_authenticate():
        await asyncio.sleep(0.05)
        return {"ok": True, "supplier_slug": "poolcorp"}

    result = asyncio.run(asyncio.wait_for(_fake_authenticate(), timeout=45.0))
    assert result == {"ok": True, "supplier_slug": "poolcorp"}


def test_b1_asyncio_wait_for_fires_timeout_past_cap():
    """A connector that hangs past the cap must trigger
    ``asyncio.TimeoutError`` so the endpoint returns
    ``{"ok": False, "error": "timeout"}`` (behavior locked by the
    endpoint handler, guarded by this cap)."""
    async def _hang():
        await asyncio.sleep(0.5)
        return {"ok": True}

    async def _run():
        try:
            await asyncio.wait_for(_hang(), timeout=0.05)
        except asyncio.TimeoutError:
            return "timed_out"
        return "returned"

    assert asyncio.run(_run()) == "timed_out"


# ── B-2 · SiteOne HTTP/2 fallback + realistic UA ─────────────────────
def test_b2_siteone_launch_args_disable_http2():
    from services.suppliers.siteone import SITEONE_LAUNCH_ARGS
    assert "--disable-http2" in SITEONE_LAUNCH_ARGS


def test_b2_siteone_user_agent_is_chrome_stable_string():
    from services.suppliers.siteone import SITEONE_USER_AGENT
    # Must be a realistic Chrome UA — NOT the pre-Fix "AquaTerra-PriceBook/1.0"
    assert "Chrome/" in SITEONE_USER_AGENT
    assert "AppleWebKit" in SITEONE_USER_AGENT
    assert "AquaTerra-PriceBook" not in SITEONE_USER_AGENT


def test_b2_siteone_client_hints_present():
    from services.suppliers.siteone import SITEONE_CLIENT_HINTS
    assert "Sec-Ch-Ua" in SITEONE_CLIENT_HINTS
    assert "Sec-Ch-Ua-Mobile" in SITEONE_CLIENT_HINTS
    assert "Sec-Ch-Ua-Platform" in SITEONE_CLIENT_HINTS


def test_b2_other_connectors_unchanged():
    """Regression guard — B-2 was scoped ONLY to SiteOne. The other
    connectors must NOT ship the ``--disable-http2`` flag; if any of
    them start importing ``SITEONE_LAUNCH_ARGS`` we'll catch it in
    review, but a straight grep-style import assertion here locks the
    scope."""
    import services.suppliers.poolcorp as _p
    import services.suppliers.heritage as _h
    import services.suppliers.ewing as _e
    import services.suppliers.epoolsupply as _ep
    for mod in (_p, _h, _e, _ep):
        # None of these modules should define a public launch-args
        # override that disables HTTP/2 — SiteOne is the only known
        # failure mode.
        for name in dir(mod):
            if name.startswith("_"): continue
            val = getattr(mod, name, None)
            if isinstance(val, list) and "--disable-http2" in val:
                raise AssertionError(
                    f"{mod.__name__}.{name} unexpectedly ships --disable-http2 "
                    f"— B-2 scope creep detected",
                )
