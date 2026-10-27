"""TD-invalidates-offline-bundle-forwardref-safe · Feb-2026 (RR).

Regression-lock for the 7 ``@invalidates_offline_bundle`` decorations
in ``routers.jobs`` / ``routers.quotes``.

Background
----------
The sibling TD ``TD-invoice-edit-forwardref · Feb-2026`` captured an
``openapi.json`` 500 that fired when ``@invalidates_offline_bundle``
wrapped ``patch_invoice``: ``@functools.wraps`` combined with a
``body: InvoiceEditBody = Body(...)`` annotation where
``InvoiceEditBody`` was defined inside the module's local scope
(not module-top-level) made FastAPI's schema builder see
``Annotated[ForwardRef('InvoiceEditBody'), Body(...)]`` and
Pydantic raised ``PydanticUserError`` on every schema
introspection call.

The fix shipped at ``routers/invoice_edit.py:20-50`` *sidestepped
the decorator entirely* on ``patch_invoice`` and substituted an
inline helper (``_invalidate_offline_bundle_for_user``) that
mirrors the decorator's runtime semantics exactly.  The 7
remaining decorated handlers were deemed safe because every one
of their body annotations is a module-top-level Pydantic model
whose name resolves at schema-build time without the ForwardRef
dance (see the ``TD-invalidates-offline-bundle-forwardref-safe``
recon notes).

What this test locks
--------------------
This file is the audit-moot regression lock established in RR:

1. **Decoration-set lock.**  Walks every file under
   ``backend/routers/`` with a grep + line-walker; collects every
   ``@invalidates_offline_bundle`` decoration (file / line / handler
   name).  Asserts the discovered set equals the frozen Feb-2026
   7-handler set listed in :data:`_FROZEN_DECORATIONS`.  A future
   dev who adds an 8th decoration MUST update that constant — the
   failure message points directly at the new entry so the review
   step surfaces the addition.

2. **Body-annotation ForwardRef lock.**  For each decorated handler
   whose signature carries a ``body:`` kwarg (4 of the 7),
   ``typing.get_type_hints(handler, include_extras=True)`` must
   resolve without raising ``NameError`` / ``AttributeError``.  A
   future handler added under ``@invalidates_offline_bundle`` with
   a locally-nested Pydantic model will fire here *before* the
   openapi schema build 500s in production.

3. **Full ``app.openapi()`` build.**  Sibling guard to
   ``test_td_invoice_edit_openapi_build.py`` but scoped to the
   7-handler surface this TD covers.  The invoice_edit test
   covers the same wall from the ``patch_invoice`` angle; this one
   covers it from the "all decorations collectively still build"
   angle.

Fix pattern on failure
----------------------
If this file ever fails at `_test_body_annotations_resolve`, the
canonical fix is the inline-helper sidestep used by
``TD-invoice-edit-forwardref``:

* Remove ``@invalidates_offline_bundle`` from the offending handler.
* Add a module-private helper mirroring the shape at
  ``routers/invoice_edit.py:28-48`` (``_invalidate_offline_bundle_for_user``).
* Call the helper at every success-return path.

Do NOT attempt to rewrite ``invalidates_offline_bundle`` with
``typing.get_type_hints`` / ``globalns`` threading — the decorator
does not inspect annotations today (see RR Phase 1 receipt).  The
root cause is FastAPI's schema builder's interaction with
``@functools.wraps`` + locally-defined ``Body(...)`` types, not
anything the decorator itself reads.
"""
from __future__ import annotations

import inspect
import re
import typing
from pathlib import Path
from typing import Tuple

import pytest


# ─── Frozen decoration set ────────────────────────────────────────
#
# File path is given relative to ``/app`` so the test is portable
# regardless of where ``pytest`` is launched from.  Line numbers are
# locked intentionally per the RR scope: a routine edit in
# ``routers/jobs.py`` / ``routers/quotes.py`` that shifts a decorated
# handler up or down WILL fail this assertion, forcing a conscious
# update of this constant and a review of whether anything else about
# the decoration shape changed.
#
# Shape: ``(file_rel_to_app, line_number, handler_name)``.

_FROZEN_DECORATIONS: Tuple[Tuple[str, int, str], ...] = (
    ("backend/routers/quotes.py",  677, "create_quote"),
    ("backend/routers/quotes.py", 2216, "update_quote_status"),
    ("backend/routers/quotes.py", 3552, "delete_quote"),
    ("backend/routers/jobs.py",   1625, "create_job"),
    ("backend/routers/jobs.py",   2581, "update_job"),
    ("backend/routers/jobs.py",   3585, "delete_job"),
    ("backend/routers/jobs.py",   3687, "patch_job_edit_window"),
)


_APP_ROOT = Path(__file__).resolve().parents[2]   # ``/app``
_BE_ROUTERS = _APP_ROOT / "backend" / "routers"

# Match: ``@invalidates_offline_bundle`` on one line, then
# ``(async )?def NAME(`` on the next line.  Allows for a decorator
# stack above (we only care about the LAST decorator being
# ``@invalidates_offline_bundle`` immediately above the def).
_DECORATION_RE = re.compile(
    r"^@invalidates_offline_bundle\s*$\s*^(?:async\s+)?def\s+"
    r"(?P<name>\w+)\s*\(",
    re.MULTILINE,
)


def _walk_decorations() -> Tuple[Tuple[str, int, str], ...]:
    """Discover every ``@invalidates_offline_bundle`` decoration in
    ``backend/routers/`` as ``(file_rel, line, handler)`` triples
    sorted by (file_rel, line) ascending.
    """
    found: list[Tuple[str, int, str]] = []
    for py_file in sorted(_BE_ROUTERS.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for m in _DECORATION_RE.finditer(text):
            # ``line`` is the 1-indexed line of the ``@`` sigil, not
            # the ``def`` — this matches how a reader eye-greps the
            # file and how the operator's Phase-1 receipt reported
            # line numbers.
            line = text[: m.start()].count("\n") + 1
            file_rel = str(py_file.relative_to(_APP_ROOT))
            found.append((file_rel, line, m.group("name")))
    return tuple(sorted(found))


# ─── Lock 1 · Decoration-set equality ─────────────────────────────

def test_decoration_set_matches_frozen_feb_2026_set() -> None:
    """A future dev adding an 8th decoration (or removing one of the
    current 7) must update ``_FROZEN_DECORATIONS`` above.  The
    assertion message spells out exactly which entries changed so
    the review path is obvious.
    """
    discovered = _walk_decorations()
    frozen = tuple(sorted(_FROZEN_DECORATIONS))

    if discovered != frozen:
        _added   = sorted(set(discovered) - set(frozen))
        _removed = sorted(set(frozen) - set(discovered))
        msg_lines = [
            "@invalidates_offline_bundle decoration set drift "
            "detected — update _FROZEN_DECORATIONS in this file.",
            "",
            "Added decorations (present in tree, absent in frozen):",
        ]
        msg_lines += [f"  + {t}" for t in _added] or ["  (none)"]
        msg_lines += ["", "Removed decorations (present in frozen, "
                      "absent in tree):"]
        msg_lines += [f"  - {t}" for t in _removed] or ["  (none)"]
        msg_lines += [
            "",
            "If adding an 8th handler: audit the body annotation "
            "shape per the RR Phase 1 receipt (module-top-level "
            "Pydantic model = safe; locally-nested = must sidestep "
            "the decorator per the TD-invoice-edit-forwardref "
            "pattern at routers/invoice_edit.py:20-50).",
        ]
        raise AssertionError("\n".join(msg_lines))


def test_decoration_set_has_exactly_seven_entries() -> None:
    """Belt + braces check — the RR audit established the handler
    count at 7.  Guards against the frozen-set constant itself being
    edited in a way that drifts off 7 without a conscious review.
    """
    assert len(_FROZEN_DECORATIONS) == 7, (
        f"RR locked the decorated-handler count at 7; the frozen "
        f"set currently has {len(_FROZEN_DECORATIONS)}.  Update "
        f"this count assertion deliberately as part of any add/"
        f"remove, so a merge conflict surfaces the review step.")


# ─── Lock 2 · Body-annotation ForwardRef resolution ───────────────
#
# Only 4 of the 7 handlers carry a ``body:`` kwarg today; the other
# 3 (``update_quote_status``, ``delete_quote``, ``delete_job``) use
# path + query params only.  We parameterise over all 7 and simply
# assert that `get_type_hints` succeeds for every handler, regardless
# of whether a body is present.  This makes the test resilient to a
# future change that adds / removes a body on any of the 7.

_HANDLER_IMPORT_PATHS: Tuple[Tuple[str, str], ...] = (
    ("backend.routers.quotes", "create_quote"),
    ("backend.routers.quotes", "update_quote_status"),
    ("backend.routers.quotes", "delete_quote"),
    ("backend.routers.jobs",   "create_job"),
    ("backend.routers.jobs",   "update_job"),
    ("backend.routers.jobs",   "delete_job"),
    ("backend.routers.jobs",   "patch_job_edit_window"),
)


@pytest.mark.parametrize("module_path,handler_name",
                         _HANDLER_IMPORT_PATHS)
def test_body_annotation_resolves_without_forwardref_error(
        module_path: str, handler_name: str) -> None:
    """``typing.get_type_hints`` must succeed for every decorated
    handler.  A locally-nested Pydantic model in the body annotation
    (the class of bug that originally 500'd ``/api/openapi.json``
    for ``patch_invoice``) would fire a ``NameError`` here before
    the decoration ever reached FastAPI's schema builder in a live
    container.
    """
    # Import the module through ``server.py`` first so the full
    # FastAPI include path is executed exactly as it is in a running
    # container.  ``server`` is the canonical app-boot entrypoint.
    import importlib
    import server  # noqa: F401 — ensures the full include graph is
                   #              realized before we type-hint-poke.

    # Strip the leading ``backend.`` because ``server.py`` lives
    # inside ``/app/backend`` and imports siblings as top-level
    # modules (e.g. ``routers.jobs``, not ``backend.routers.jobs``).
    _effective_module = module_path.replace("backend.", "", 1)
    module = importlib.import_module(_effective_module)
    handler = getattr(module, handler_name)
    assert callable(handler), (
        f"{module_path}::{handler_name} is not callable — the "
        f"decoration shape may have changed")

    # ``inspect.unwrap`` peels ``@functools.wraps`` layers so we see
    # the inner coroutine's real annotations (the decorator wraps
    # with ``@wraps(func)``).  Without ``unwrap`` we'd be inspecting
    # ``_wrapper(*args, **kwargs)`` which has no annotations.
    inner = inspect.unwrap(handler)

    try:
        hints = typing.get_type_hints(inner, include_extras=True)
    except NameError as exc:
        raise AssertionError(
            f"ForwardRef resolution failed on "
            f"{module_path}::{handler_name} — body or param "
            f"annotation references a name that does not resolve "
            f"at get_type_hints time: {exc!r}.  Fix pattern: "
            f"sidestep @invalidates_offline_bundle on this handler "
            f"and use the inline-helper pattern from "
            f"routers/invoice_edit.py:20-50 (see TD-invoice-edit-"
            f"forwardref · Feb-2026)."
        ) from exc
    except AttributeError as exc:
        raise AssertionError(
            f"get_type_hints raised AttributeError on "
            f"{module_path}::{handler_name}: {exc!r}.  Likely a "
            f"malformed annotation — audit the handler's signature."
        ) from exc

    # ``hints`` must at minimum contain the handler's return
    # annotation OR at least one param annotation — a totally
    # empty dict suggests ``inspect.unwrap`` didn't find the inner
    # function, which would silently hide a regression.
    assert hints or inner is not handler, (
        f"{module_path}::{handler_name} produced an empty "
        f"get_type_hints result AND inspect.unwrap returned the "
        f"outer wrapper (not the inner handler) — the "
        f"@functools.wraps chain may have broken and the test "
        f"would silently miss a ForwardRef regression.  Audit the "
        f"decoration manually."
    )


# ─── Lock 3 · Full app.openapi() build ────────────────────────────

def test_app_openapi_builds_end_to_end() -> None:
    """Sibling to ``test_td_invoice_edit_openapi_build::
    test_openapi_schema_builds_after_patch_invoice_decorator_removal``
    but scoped to this TD's audit framing: the 7 decorated handlers
    collectively must not re-introduce the ``PydanticUserError`` /
    ``ForwardRef`` 500 that originally fired on
    ``/api/openapi.json``.

    If ``test_td_invoice_edit_openapi_build`` passes but this test
    fails, that's informative: the regression is in one of the 7
    handlers under this TD, not in ``patch_invoice``.
    """
    import server
    schema = server.app.openapi()
    assert schema.get("openapi"), (
        "openapi version missing — schema builder returned a "
        "truncated / malformed result")

    paths = schema.get("paths") or {}

    # Spot-check: a representative route for each of the two
    # decorated router modules must be reachable in the schema.
    # These are the create-path endpoints for both ``jobs`` and
    # ``quotes`` — if either is absent, the schema built but the
    # router include ate the decorated handler, which is itself a
    # regression worth surfacing.
    _expected_representative_paths = ("/api/jobs", "/api/quotes")
    for p in _expected_representative_paths:
        assert p in paths, (
            f"{p} missing from app.openapi().paths — one of the 7 "
            f"decorated handlers' router modules failed to include. "
            f"Full path keys (first 20): "
            f"{sorted(paths.keys())[:20]}")
