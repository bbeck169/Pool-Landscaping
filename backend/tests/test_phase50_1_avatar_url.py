"""Phase 50.1 · Feb-2026 — ``avatar_url`` parity guard.

Asserts that ``GET /api/ai-ops/employees`` returns an ``avatar_url``
key on every row (may be ``null``, never missing) so the web + mobile
AI Employees cards can uniformly layer a static image over the shared
Lottie backdrop.
"""
from __future__ import annotations

import os
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://poolscape-audit.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@aquaterra.com"
PASSWORD = "password123"


def _login(email: str = ADMIN_EMAIL) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token")
    assert tok, f"no token in response: {body}"
    return tok


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_ai_ops_employees_returns_avatar_url_key_on_every_row():
    """Every row must carry the ``avatar_url`` key — may be ``None``
    (JSON ``null``) but never missing. Enforces the Phase 50.1
    web/mobile parity contract."""
    tok = _login()
    r = requests.get(f"{API}/ai-ops/employees", headers=_h(tok), timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and rows, f"expected non-empty list, got {rows!r}"
    for row in rows:
        assert "avatar_url" in row, (
            f"row {row.get('key') or row.get('id')} is missing the "
            f"``avatar_url`` key (Phase 50.1 contract)"
        )
        v = row["avatar_url"]
        assert v is None or isinstance(v, str), (
            f"avatar_url must be null or string, got {type(v).__name__}: {v!r}"
        )
        # If a value is present it must be either an absolute URL or
        # an app-relative path — never an empty string.
        if isinstance(v, str):
            assert v.strip() != "", "avatar_url must not be empty string"


def test_seeded_default_personas_have_relative_avatar_paths():
    """Sanity — the shipped seed manifest points every persona at
    ``/avatars/personas/{key}.jpg``. Guards against a future refactor
    accidentally nuking the default images."""
    tok = _login()
    r = requests.get(f"{API}/ai-ops/employees", headers=_h(tok), timeout=30)
    assert r.status_code == 200
    rows = r.json()
    default_paths = [
        row["avatar_url"] for row in rows
        if isinstance(row.get("avatar_url"), str)
        and row["avatar_url"].startswith("/avatars/personas/")
    ]
    assert default_paths, (
        "expected at least one persona with a default "
        "``/avatars/personas/*.jpg`` avatar_url"
    )
