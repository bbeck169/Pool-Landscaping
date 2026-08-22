"""Feb-2026 · P16B — coverage for the shared ``client_ip`` helper.

Extracted from ``routers/auth.py`` + ``routers/customer_account.py``
after both local copies drifted (different fallback strings).  The
shared helper preserves each caller's exact fallback via the
``default`` kwarg; these three branch tests pin the contract.
"""
from types import SimpleNamespace

from services._shared.http import client_ip


def _mk_request(*, xff: str = "", host: str | None = None):
    """Build a minimal ``fastapi.Request``-shaped object.  We only
    exercise the two attributes ``client_ip`` reads."""
    headers = {}
    if xff:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=host) if host is not None else None,
    )


def test_client_ip_prefers_first_hop_of_xff():
    """When X-Forwarded-For is set, the first hop wins — every
    downstream socket IP (Cloudflare edge, load balancer) is stripped."""
    req = _mk_request(
        xff="203.0.113.5, 10.0.0.1, 10.0.0.2", host="10.0.0.2",
    )
    assert client_ip(req) == "203.0.113.5"


def test_client_ip_falls_back_to_request_client_host_when_no_xff():
    """Direct-socket case — no proxy header, use the peer IP."""
    req = _mk_request(host="198.51.100.9")
    assert client_ip(req) == "198.51.100.9"


def test_client_ip_returns_default_when_neither_source_present():
    """No X-Forwarded-For AND no ``request.client`` → the ``default``
    sentinel fires.  Auth uses ``"unknown"``; customer_account uses
    ``""``; both are covered by the branch."""
    req = _mk_request()
    assert client_ip(req) == "unknown"                # implicit default
    assert client_ip(req, default="") == ""            # customer-account
    assert client_ip(req, default="unknown") == "unknown"  # auth
