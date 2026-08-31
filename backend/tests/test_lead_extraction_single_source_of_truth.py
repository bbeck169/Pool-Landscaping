"""Phase F5 · Feb-2026 — DRY consolidation identity lock.

Both public-form (``routers/marketing.py``) and widget-form
(``routers/marketing_forms.py``) MUST resolve to the SAME extractor
function object from ``services/lead_extraction``.  If a future
refactor accidentally re-defines a local ``_first_str`` or
``_lead_row_from_form_values`` in either router, this test fires.
"""
from __future__ import annotations

from routers import marketing as m
from routers import marketing_forms as mf
from services import lead_extraction as le


def test_marketing_first_str_is_shared_module_function():
    # ``routers.marketing._first_str`` is imported from the shared
    # module, so ``is`` identity should hold.
    assert m._first_str is le.first_str


def test_marketing_lead_row_is_shared_module_function():
    assert m._lead_row_from_form_values is le.lead_row_from_form_values


def test_marketing_forms_uses_extract_contact_fields_symbol():
    """The widget path uses ``extract_contact_fields`` inline via a
    local import — grep the source file for the identifier so a
    refactor away from the shared helper is caught."""
    import pathlib
    src = pathlib.Path(mf.__file__).read_text(encoding="utf-8")
    assert "from services.lead_extraction import extract_contact_fields" in src, \
        "widget-form path must import the shared extractor"
    # And it must NOT re-define a local extractor.
    # (The narrow ``_first_str`` helper still exists but must call
    #  the shared one — check the delegation.)
    assert "_shared_first_str(d, keys)" in src, \
        "local _first_str must delegate to the shared module"


def test_shared_module_exports_public_names():
    """The public API surface is stable — locking the exported
    symbol names so downstream imports don't need to change on a
    minor refactor."""
    for name in ("first_str", "lead_row_from_form_values",
                  "extract_contact_fields", "compose_name",
                  "WEBSITE_VISITOR_FALLBACK"):
        assert hasattr(le, name), f"lead_extraction missing {name}"
