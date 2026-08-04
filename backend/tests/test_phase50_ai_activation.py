"""Phase 50 · Feb-2026 — AI employee activation + Lottie avatar guards."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from types import SimpleNamespace


# ── Migration idempotency ─────────────────────────────────────────────
def test_activation_backfill_flips_only_inactive_rows():
    from backend.scripts.phase50_activate_ai_employees import activate_all_ai_employees
    ai_employees = MagicMock()
    ai_employees.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=3))
    db = MagicMock(ai_employees=ai_employees)
    n = asyncio.get_event_loop().run_until_complete(activate_all_ai_employees(db))
    assert n == 3
    # Query filter matches inactive/missing/null active — not active=true.
    call_filter = ai_employees.update_many.await_args.args[0]
    assert "$or" in call_filter


def test_activation_backfill_is_idempotent():
    """Second run must flip zero rows — the query filter excludes
    active=true rows."""
    from backend.scripts.phase50_activate_ai_employees import activate_all_ai_employees
    ai_employees = MagicMock()
    ai_employees.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
    db = MagicMock(ai_employees=ai_employees)
    n = asyncio.get_event_loop().run_until_complete(activate_all_ai_employees(db))
    assert n == 0


# ── Seed guard ────────────────────────────────────────────────────────
def test_seed_module_default_is_active_true():
    """Regression guard — a fresh env must never come up with an
    inactive AI employee."""
    import inspect
    from routers import ai_employees as mod
    src = inspect.getsource(mod.seed_ai_employees_for_tenant)
    # The seed insert must set active=True. If a future rewrite drops
    # the key, this test trips.
    assert '"active": True' in src, "seed must set active=True"
    # And there must NOT be any active=False in the seed body.
    assert '"active": False' not in src


# ── Lottie JSON is well-formed and MIT ─────────────────────────────────
def test_lottie_idle_json_is_valid_bodymovin():
    p = Path(__file__).resolve().parents[2] / "frontend" / "src" / "assets" / "lottie" / "ai" / "idle.json"
    data = json.loads(p.read_text())
    for k in ("v", "fr", "ip", "op", "w", "h", "layers"):
        assert k in data, f"missing {k} in Lottie JSON"
    assert len(data["layers"]) >= 1


def test_lottie_json_present_on_both_surfaces():
    """Web + mobile must ship the same Lottie file so the two surfaces
    animate identically (Phase 50 parity requirement)."""
    web = Path(__file__).resolve().parents[2] / "frontend" / "src" / "assets" / "lottie" / "ai" / "idle.json"
    mob = Path(__file__).resolve().parents[2] / "mobile" / "assets" / "lottie" / "ai" / "idle.json"
    assert web.exists() and mob.exists()
    assert web.read_bytes() == mob.read_bytes(), \
        "web + mobile Lottie files must be byte-identical (parity)"
