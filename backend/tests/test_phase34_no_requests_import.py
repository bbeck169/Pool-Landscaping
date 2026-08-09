"""Phase 34-migrate-v2 · Phase 34-v2-e · Feb 2026 — guardrail.

Forbids ``import requests`` (and ``from requests import ...``) inside
any ``backend/tests/test_phase34*.py`` file. All phase34 test files
were migrated in Phases -b / -c / -d to use ``_phase34_http_shim``'s
in-process ``http`` object; regressing to network ``requests`` calls
would silently reintroduce the ``ReadTimeout`` cluster (recurrence
count > 3 sessions per the running audit) and, worse, the
``Task got Future attached to a different loop`` failure mode that
killed the v1 migration.

The rule is scoped narrowly:
    • Only inspects files matching the glob ``tests/test_phase34*.py``.
    • Excludes ``_phase34_http_shim.py`` itself (which lives in the
      same folder but is not a ``test_*`` file, so it isn't collected
      by pytest and doesn't match the glob anyway — belt-and-braces).
    • Ignores ``requests`` mentions inside string literals, comments,
      or attribute-only names (e.g. ``db.review_requests``) — the
      check is AST-based, matching only actual import statements.

Running this file is a single pytest test that either passes silently
or fails with a message listing every offending file + line number.
"""
from __future__ import annotations

import ast
import pathlib
from typing import List, Tuple


TESTS_DIR = pathlib.Path(__file__).resolve().parent
PHASE34_GLOB = "test_phase34*.py"

# Files explicitly permitted to import ``requests`` (empty by design —
# the shim uses ``httpx`` internally, not ``requests``). Kept as an
# explicit list so a future intentional exception has a documented
# home rather than a scattered per-file skip comment.
ALLOWED_FILES: set[str] = set()


def _import_requests_lines(src: str) -> List[Tuple[int, str]]:
    """Return ``[(lineno, source_line), ...]`` for every top-level
    ``import requests`` / ``from requests[.*] import ...`` in ``src``.
    Empty list means the file is clean.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # A syntax-broken test file will fail collection anyway; the
        # guardrail defers to that error rather than layering a second.
        return []
    hits: List[Tuple[int, str]] = []
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "requests" or alias.name.startswith("requests."):
                    hits.append((node.lineno, lines[node.lineno - 1]))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "requests" or mod.startswith("requests."):
                hits.append((node.lineno, lines[node.lineno - 1]))
    return hits


def test_no_requests_import_in_phase34_test_files():
    """Guardrail: every ``test_phase34*.py`` MUST use the in-process
    ``_phase34_http_shim`` and MUST NOT import ``requests``.

    If this test starts failing, either:
      • the offending file regressed to network HTTP — fix by
        swapping ``requests.*`` for ``http.*`` (see Phase 34-v2-b/c/d
        migrations for the mechanical pattern); or
      • the offending file genuinely needs ``requests`` (very
        unlikely — the shim covers get/post/put/patch/delete with
        the same signature) — in which case add its name to
        ``ALLOWED_FILES`` above with a comment explaining why.
    """
    violations: List[str] = []
    for path in sorted(TESTS_DIR.glob(PHASE34_GLOB)):
        if path.name in ALLOWED_FILES:
            continue
        # Guardrail file itself never imports ``requests``, and the
        # helper it protects is the shim.
        if path.name == pathlib.Path(__file__).name:
            continue
        hits = _import_requests_lines(path.read_text(encoding="utf-8"))
        for lineno, line in hits:
            violations.append(f"  {path.name}:{lineno}  {line.strip()}")

    assert not violations, (
        "Phase 34-v2-e guardrail: forbidden ``requests`` import(s) in "
        f"{len(violations)} phase34 test file line(s):\n"
        + "\n".join(violations)
        + "\n\nUse ``from tests._phase34_http_shim import http`` and "
        "swap ``requests.<verb>(...)`` for ``http.<verb>(...)`` — the "
        "shim is a drop-in replacement backed by an in-process "
        "ASGITransport that reuses the phase34 persistent event loop."
    )
