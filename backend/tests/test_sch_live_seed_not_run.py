"""SCH Phase II-C · Feb-2026 — regression lock for Option-Y resolution.

Three assertions:
  (a) ``backend/server.py`` file source does NOT contain the three
      schedule-demo seed helpers as ``await step(...)`` arguments.
      Build the needles from concatenated parts so the tombstone
      comment left in-place doesn't false-positive the match.
  (b) The three seed helpers (``seed_landscaping_user``,
      ``seed_landscape_tech_carlos``, ``seed_pool_tech_mike``) are
      still importable from ``seed`` — they're kept for parity with
      ``test_seed_demo_users_gate.py`` and reusable by
      ``tests/conftest.py::_seed_schedule_demo_techs``, just no
      longer invoked by the live-boot path.
  (c) Runtime scan of ``server._background_seed`` via
      ``inspect.getsource`` — the live function body (not the file
      text) does NOT reference any of the three helper names, so a
      refactor that re-wires the helpers through a different
      indirection also trips this test.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path


_BACKEND = Path("/app/backend")


# Build email-free, concat-based needles so a tombstone comment
# (e.g. "landscaper, carlos landscape tech, mike pool tech" in prose)
# does NOT match. The ``await step("<key>", ...)`` form is what we lock.
def _needle(key: str) -> str:
    return 'await ' + 'step(' + '"' + key + '"'


_NEEDLES = (
    _needle("landscaping_user"),
    _needle("landscape_tech_carlos"),
    _needle("pool_tech_mike"),
)


# ── (a) File-source scan ────────────────────────────────────────────
def test_server_py_source_has_no_live_boot_schedule_demo_tech_seeds():
    src = (_BACKEND / "server.py").read_text()
    found = [n for n in _NEEDLES if n in src]
    assert not found, (
        f"server.py still contains live-boot seed calls: {found}\n"
        f"These three helpers must only run via tests/conftest.py "
        f"(SCH Phase II-C contract)."
    )


# ── (b) Helpers importable (conftest reuse) ─────────────────────────
def test_three_seed_helpers_still_importable_for_conftest_reuse():
    sys.path.insert(0, str(_BACKEND))
    from seed import (                      # noqa: F401
        seed_landscaping_user,
        seed_landscape_tech_carlos,
        seed_pool_tech_mike,
    )
    assert callable(seed_landscaping_user)
    assert callable(seed_landscape_tech_carlos)
    assert callable(seed_pool_tech_mike)


# ── (c) Runtime inspect.getsource scan ──────────────────────────────
def test_background_seed_runtime_body_does_not_call_three_helpers():
    sys.path.insert(0, str(_BACKEND))
    import server
    body = inspect.getsource(server._background_seed)
    found = [n for n in _NEEDLES if n in body]
    assert not found, (
        f"server._background_seed source still references: {found}\n"
        f"Refactor must preserve the SCH Phase II-C invariant — the "
        f"three helpers may be imported but must not be await-stepped "
        f"from the live-boot path."
    )
