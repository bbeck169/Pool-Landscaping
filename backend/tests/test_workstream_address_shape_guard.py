"""TD-66 · Feb-2026 — Workstream property-address shape guard.

Preview-tenant Mongo rows surfaced a historical import-drift bug: some
``db.properties`` docs store ``address`` as a plain string (free-form
"123 Fake St, Austin") instead of the canonical ``{line1, city, state,
postal_code}`` dict.  Pre-TD-66, the Workstream `/jobs` list did
``addr = prop.get("address") or {}; addr.get("line1")`` — which raises
``AttributeError: 'str' object has no attribute 'get'`` on the string
rows and poisons the entire paginated response with HTTP 500.

Operator Q3=C decision: log and recover gracefully, never crash.  The
helper ``_prop_address_label`` is the single resolver for the
``property_address`` field on the Workstream list rows; this file
pins its 5-shape contract.

Operator-visible log line (verified in test 2):
    [workstream] property <pid> non-dict address <type> · value=<repr> · TD-66

Operator grep:
    grep "non-dict address" /var/log/supervisor/backend.*.log
"""
from __future__ import annotations

import logging

from routers.workstream import _prop_address_label


# ═══════════════════════════════════════════════════════════════════
# 1 · Canonical dict shape — joins line1 · city · state · postal.
# ═══════════════════════════════════════════════════════════════════
def test_dict_address_joins_canonical_fields():
    prop = {
        "id": "p_dict",
        "address": {
            "line1": "742 Evergreen Terrace",
            "city": "Springfield",
            "state": "OR",
            "postal_code": "97403",
        },
    }
    label = _prop_address_label(prop, "p_dict")
    assert label == "742 Evergreen Terrace, Springfield, OR, 97403"


# ═══════════════════════════════════════════════════════════════════
# 2 · String-shape address — no crash, emits TD-66 warning, returns
#     the raw string so the UI row still shows something.
# ═══════════════════════════════════════════════════════════════════
def test_string_address_emits_td66_warning_and_recovers(caplog):
    prop = {"id": "p_str", "address": "123 Fake St, Austin, TX"}
    with caplog.at_level(logging.WARNING):
        label = _prop_address_label(prop, "p_str")

    assert label == "123 Fake St, Austin, TX"
    # Operator-visible log line (grep "non-dict address").
    matched = [r for r in caplog.records if "non-dict address" in r.getMessage()]
    assert matched, f"expected TD-66 warning, got: {[r.getMessage() for r in caplog.records]}"
    msg = matched[0].getMessage()
    assert "property p_str" in msg
    assert "TD-66" in msg
    assert "'123 Fake St, Austin, TX'" in msg  # value=%r preserves quotes


# ═══════════════════════════════════════════════════════════════════
# 3 · ``address: None`` — returns None silently (no log spam).
# ═══════════════════════════════════════════════════════════════════
def test_none_address_returns_none_silently(caplog):
    prop = {"id": "p_none", "address": None}
    with caplog.at_level(logging.WARNING):
        label = _prop_address_label(prop, "p_none")
    assert label is None
    assert not [r for r in caplog.records if "non-dict address" in r.getMessage()]


# ═══════════════════════════════════════════════════════════════════
# 4 · Empty dict ``{}`` — returns None (join of nothing is empty).
# ═══════════════════════════════════════════════════════════════════
def test_empty_dict_address_returns_none():
    prop = {"id": "p_empty_dict", "address": {}}
    assert _prop_address_label(prop, "p_empty_dict") is None


# ═══════════════════════════════════════════════════════════════════
# 5 · Missing ``address`` field entirely — returns None.
#     Also exercises the ``prop is None`` branch — the Workstream
#     list calls this with ``prop = pmap.get(pid)`` which is None
#     when the property row was deleted but the job still references
#     the pid.
# ═══════════════════════════════════════════════════════════════════
def test_missing_address_field_and_none_prop_return_none(caplog):
    # (a) prop dict without an ``address`` key.
    assert _prop_address_label({"id": "p_missing"}, "p_missing") is None
    # (b) prop itself is None (deleted/legacy row).
    with caplog.at_level(logging.WARNING):
        assert _prop_address_label(None, None) is None
    assert not [r for r in caplog.records if "non-dict address" in r.getMessage()]
