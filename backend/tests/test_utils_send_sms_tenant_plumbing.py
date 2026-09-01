"""Phase G2 · Feb-2026 (TD-G1-1) — `utils.send_sms` tenant plumbing.

Locks three invariants:

1. **Signature contract** — `utils.send_sms(to, body, *, tenant_id=None)`.
   The kwarg MUST be optional (backward-compat) and keyword-only (no
   positional 3rd arg collisions with `mms_url` etc. that older
   forks may have shipped).

2. **Boundary contract** — when `utils.send_sms` is called with
   `tenant_id`, the RC adapter's `send(...)` receives the same
   `tenant_id` in its kwargs. Locked via monkeypatch capture of the
   adapter call.

3. **Grep regression** — every `send_sms(...)` call site in
   `backend/` that references `utils.send_sms` (import or dotted)
   must either
     a) pass `tenant_id=` as a kwarg, OR
     b) carry a `# tenant_id:` comment within 3 lines above or on
        the same line, explicitly documenting why plumbing is
        infeasible at that site.
   The `services.comms_sms_adapter.send_sms` variant is a different
   symbol (async, first positional arg IS tenant_id) and is
   excluded from the grep.
"""
from __future__ import annotations

import inspect
import os
import re
from pathlib import Path

import pytest


# ═════════════════════════ Invariant 1 · signature ══════════════════════
def test_utils_send_sms_signature_has_optional_tenant_id_kwarg():
    import utils as _utils
    sig = inspect.signature(_utils.send_sms)
    params = sig.parameters
    assert "tenant_id" in params, (
        f"utils.send_sms is missing the tenant_id kwarg introduced in "
        f"Phase G2 · TD-G1-1. Current signature: {sig}"
    )
    p = params["tenant_id"]
    # Must be optional (default None) and keyword-only.
    assert p.default is None, (
        f"tenant_id must default to None (optional); got {p.default!r}"
    )
    assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
        f"tenant_id must be KEYWORD_ONLY (behind ``*,``); got {p.kind}"
    )


# ══════════════════════ Invariant 2 · boundary contract ═════════════════
def test_utils_send_sms_forwards_tenant_id_to_rc_adapter(monkeypatch):
    """When `utils.send_sms(..., tenant_id=X)` runs, the RC adapter
    call must see ``tenant_id=X`` in its kwargs."""
    captured = {}

    async def _fake_rc_send(*args, **kwargs):
        captured.update(kwargs)
        return {"provider": "ringcentral",
                "provider_status": "sent",
                "id": "boundary-capture"}

    # Both places `utils.send_sms` might import from.
    import services.sms.rc_adapter as _mod
    monkeypatch.setattr(_mod, "send", _fake_rc_send, raising=False)

    import utils as _utils
    ok = _utils.send_sms(
        "+16028874400", "boundary contract",
        tenant_id="tenant-under-test",
    )
    assert ok is True, "adapter returned success; helper should return True"
    assert captured.get("tenant_id") == "tenant-under-test", (
        f"tenant_id lost between utils.send_sms and rc_adapter.send; "
        f"captured kwargs: {captured!r}"
    )
    # Sanity: `to`, `body`, `category` also plumbed correctly.
    assert captured.get("to") == "+16028874400"
    assert captured.get("body") == "boundary contract"
    assert captured.get("category") == "transactional"


# ══════════════════════ Invariant 3 · grep regression ══════════════════
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_CALL_RE = re.compile(r"(?<![.\w])send_sms\s*\(", re.MULTILINE)


def _iter_backend_py_files():
    for root, dirs, files in os.walk(_BACKEND_ROOT):
        # Skip test files, pycache, venv, node_modules.
        parts = set(Path(root).parts)
        if "tests" in parts or "__pycache__" in parts or "node_modules" in parts:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            if f.startswith("test_"):
                continue
            yield Path(root) / f


def _file_uses_utils_send_sms(path: Path) -> bool:
    """Detects modules that import ``send_sms`` from ``utils`` (the
    legacy sync helper). Ignores modules that use
    ``services.comms_sms_adapter.send_sms`` — that variant is a
    different symbol whose first positional arg IS tenant_id."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    # Direct: `from utils import ..., send_sms, ...`
    if re.search(
        r"^\s*from\s+utils\s+import\s+[^\n#]*\bsend_sms\b",
        src, re.MULTILINE,
    ):
        return True
    # `import utils` + `utils.send_sms(...)`
    if re.search(r"^\s*import\s+utils\b", src, re.MULTILINE) and \
            re.search(r"\butils\.send_sms\s*\(", src):
        return True
    return False


def _line_or_neighbours_have_annotation(lines, idx: int) -> bool:
    """A ``# tenant_id:`` comment on this line or the 3 lines above
    counts as an intentional annotation."""
    lo = max(0, idx - 3)
    for i in range(lo, idx + 1):
        if "# tenant_id:" in lines[i]:
            return True
    return False


def _has_tenant_id_kwarg_in_call(src: str, start_idx: int) -> bool:
    """Peek ahead from the `send_sms(` position and check the balanced
    argument list for ``tenant_id=``.
    """
    # Advance to the opening paren.
    m = re.compile(r"send_sms\s*\(").search(src, start_idx)
    if not m:
        return False
    depth = 0
    end = None
    for i, ch in enumerate(src[m.end() - 1:], start=m.end() - 1):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return False
    return "tenant_id=" in src[m.end():end]


def test_every_utils_send_sms_caller_passes_tenant_id_or_annotates():
    offenders = []
    for path in _iter_backend_py_files():
        # Only inspect files that actually use ``utils.send_sms``.
        if not _file_uses_utils_send_sms(path):
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        for match in _CALL_RE.finditer(src):
            call_char_idx = match.start()
            # Skip the definition itself in ``utils.py``.
            line_no = src.count("\n", 0, call_char_idx)  # 0-indexed
            line_txt = lines[line_no] if line_no < len(lines) else ""
            if "def send_sms" in line_txt:
                continue
            # Skip lines that clearly reference ``comms_sms_adapter``
            # (rare but possible if a file mixes both imports).
            if "comms_sms_adapter" in line_txt:
                continue
            if _has_tenant_id_kwarg_in_call(src, call_char_idx):
                continue
            if _line_or_neighbours_have_annotation(lines, line_no):
                continue
            rel = path.relative_to(_BACKEND_ROOT)
            offenders.append(f"{rel}:{line_no + 1}: {line_txt.strip()}")

    assert not offenders, (
        "Phase G2 · TD-G1-1 grep regression — the following "
        "``utils.send_sms`` call sites neither pass ``tenant_id=`` "
        "nor carry a ``# tenant_id: <reason>`` annotation within "
        "the 3 lines above:\n  " + "\n  ".join(offenders)
    )
