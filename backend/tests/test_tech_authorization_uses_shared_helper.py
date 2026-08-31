"""Feb-2026 · Phase F3 · Contract test — every 'Not your job' gate
routes through the shared crew-aware helper.

AST-scans every ``routers/*.py`` file plus ``services/mobile_sync``
(if it existed) for the exact pattern:

    raise HTTPException(403, "Not your job")

and verifies that the surrounding function body ALSO contains a
call to ``is_tech_authorized_on_job``. Any file that raises the
403 without going through the helper fails the test — this makes
it impossible to reintroduce the inline
``job.technician_id != user.technician_id`` predicate that
originally caused P0-B.

Exception classes accepted as legitimate:
  * ``customer`` role gates ("Not your job" also used for the
    customer role in a couple of endpoints — those check
    ``customer_id != user.customer_id`` which is out of scope for
    the tech helper). The check inspects the ``if`` predicate on
    the sibling line: a ``role == "customer"`` predicate is fine.
"""
from __future__ import annotations

import ast
import pathlib
from typing import List

REPO_ROUTERS = pathlib.Path(__file__).resolve().parents[1] / "routers"

# The gates the test defends against — every single one across
# jobs.py + the mirrors.
_ERROR_STRING = "Not your job"
_HELPER_NAME = "is_tech_authorized_on_job"


def _iter_router_files() -> List[pathlib.Path]:
    return sorted(REPO_ROUTERS.glob("*.py"))


def _is_customer_gate(if_node: ast.If) -> bool:
    """Return True if the enclosing ``if`` predicate is a customer
    role/ownership check — legitimately raises "Not your job"
    without needing the tech helper."""
    src = ast.unparse(if_node.test)
    src_lower = src.lower()
    return (
        '"customer"' in src_lower
        or "'customer'" in src_lower
        or "customer_id" in src_lower
    )


def _function_calls(fn_node: ast.AST) -> set:
    """Return the set of function-names called anywhere in ``fn_node``."""
    names: set = set()
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name:
                names.add(name)
    return names


def _function_uses_helper(fn_node: ast.AST, module: ast.AST) -> bool:
    """Return True iff ``fn_node`` calls ``is_tech_authorized_on_job``
    DIRECTLY or through a same-module shim (e.g.,
    ``job_media_line_items.py::_tech_can_touch`` which itself
    delegates to the helper). Walks one level of indirection so a
    small shim/adapter helper is treated as compliant.
    """
    direct = _function_calls(fn_node)
    if _HELPER_NAME in direct:
        return True

    # Build a map of local function name → node so we can chase
    # same-module indirections.
    local_funcs = {
        node.name: node
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for called in direct:
        shim = local_funcs.get(called)
        if shim is None:
            continue
        if _HELPER_NAME in _function_calls(shim):
            return True
    return False


def _enclosing_function(module: ast.AST, target: ast.AST):
    """Return the FunctionDef/AsyncFunctionDef that contains ``target``."""
    for candidate in ast.walk(module):
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(candidate):
                if child is target:
                    return candidate
    return None


def _enclosing_if(module: ast.AST, target: ast.AST):
    for candidate in ast.walk(module):
        if isinstance(candidate, ast.If):
            for child in ast.walk(candidate):
                if child is target and child is not candidate:
                    return candidate
    return None


def _raise_matches(node: ast.Raise) -> bool:
    """Return True if the ``raise`` matches
    ``raise HTTPException(403, 'Not your job')`` (arg order flex)."""
    if not isinstance(node.exc, ast.Call):
        return False
    func = node.exc.func
    name = getattr(func, "attr", None) or getattr(func, "id", None)
    if name != "HTTPException":
        return False
    args = node.exc.args
    if not args:
        return False
    for arg in args:
        if (isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and _ERROR_STRING in arg.value):
            return True
    return False


def test_every_not_your_job_gate_uses_shared_helper():
    """Enforce F1 · shared authz helper as the single tech gate.

    A failure means somebody added a new ``raise HTTPException(
    403, "Not your job")`` without preceding it with a call to
    ``is_tech_authorized_on_job``. Fix by adding the helper call
    to the gate (see ``services/authz.py`` for the API).
    """
    violations: List[str] = []
    for path in _iter_router_files():
        src = path.read_text(encoding="utf-8")
        if _ERROR_STRING not in src:
            continue
        try:
            module = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue  # Skip malformed files — separate test catches syntax.

        for node in ast.walk(module):
            if not isinstance(node, ast.Raise):
                continue
            if not _raise_matches(node):
                continue

            enclosing_if = _enclosing_if(module, node)
            if enclosing_if is not None and _is_customer_gate(enclosing_if):
                continue  # Customer-role gate — out of tech-helper scope.

            fn = _enclosing_function(module, node)
            if fn is None:
                violations.append(
                    f"{path.name}:{node.lineno} — 'Not your job' raise "
                    "outside a function scope"
                )
                continue
            if not _function_uses_helper(fn, module):
                violations.append(
                    f"{path.name}:{node.lineno} in {fn.name}() — "
                    "raises 'Not your job' but function does not "
                    "call is_tech_authorized_on_job (directly or "
                    "via a same-module shim). Route through "
                    "services.authz.is_tech_authorized_on_job."
                )

    assert not violations, (
        "F1 tech-authz contract broken:\n  - "
        + "\n  - ".join(violations)
    )
