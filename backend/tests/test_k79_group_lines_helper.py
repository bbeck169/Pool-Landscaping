"""Phase K79 · Feb-2026 — group_lines_for_customer unit tests.

The helper is a pure function so we don't need a live DB / event loop.
"""
from __future__ import annotations

from services.quotes.customer_view import (
    build_customer_view_payload,
    group_lines_for_customer,
)


_CATS = [
    {"id": "svc-pool", "name": "Pool Cleaning"},
    {"id": "svc-lawn", "name": "Lawn Care"},
    {"id": "svc-tile", "name": "Tile & Coping"},
]


def _line(desc, qty, unit, cat_id=None, **extra):
    row = {"description": desc, "quantity": qty, "unit_price": unit}
    if cat_id:
        row["service_category_id"] = cat_id
    row.update(extra)
    return row


def test_groups_by_service_category_id_in_first_appearance_order():
    quote = {
        "line_items": [
            _line("Chlorine treatment", 1, 60, "svc-pool"),
            _line("Weekly cleaning", 4, 40, "svc-pool"),
            _line("Grout resealing", 1, 200, "svc-tile"),
        ],
    }
    groups = group_lines_for_customer(quote, _CATS)
    assert [g["category_id"] for g in groups] == ["svc-pool", "svc-tile"]
    assert groups[0]["label"] == "Pool Cleaning"
    assert groups[1]["label"] == "Tile & Coping"


def test_subtotals_sum_qty_times_unit_price():
    quote = {
        "line_items": [
            _line("Chlorine treatment", 1, 60, "svc-pool"),   # 60
            _line("Weekly cleaning", 4, 40, "svc-pool"),      # 160
            _line("Grout resealing", 1, 200, "svc-tile"),     # 200
        ],
    }
    groups = group_lines_for_customer(quote, _CATS)
    subtotals = {g["category_id"]: g["subtotal"] for g in groups}
    assert subtotals["svc-pool"] == 220.0
    assert subtotals["svc-tile"] == 200.0


def test_lines_without_category_bucket_into_other_tail():
    quote = {
        "line_items": [
            _line("Chlorine treatment", 1, 60, "svc-pool"),
            _line("Random repair", 1, 75),                    # no category
            _line("Extra mow", 2, 30, "svc-lawn"),
            _line("Handyman task", 1, 25),                    # no category
        ],
    }
    groups = group_lines_for_customer(quote, _CATS)
    # Real categories keep their first-appearance order; Other tail.
    assert [g["category_id"] for g in groups] == [
        "svc-pool", "svc-lawn", None,
    ]
    other = next(g for g in groups if g["category_id"] is None)
    assert other["label"] == "Other"
    assert other["subtotal"] == 100.0


def test_empty_string_and_null_service_category_id_both_bucket_other():
    quote = {
        "line_items": [
            _line("A", 1, 10, ""),                            # empty string
            _line("B", 1, 20, None),                          # null
            _line("C", 1, 30),                                # missing key
        ],
    }
    groups = group_lines_for_customer(quote, _CATS)
    assert len(groups) == 1
    assert groups[0]["category_id"] is None
    assert groups[0]["subtotal"] == 60.0


def test_customer_group_descriptions_wired_per_category():
    quote = {
        "line_items": [
            _line("Chlorine treatment", 1, 60, "svc-pool"),
            _line("Grout resealing", 1, 200, "svc-tile"),
        ],
        "customer_group_descriptions": {
            "svc-pool": "Includes weekly chemistry balance.",
            "svc-tile": "Wet-sealing after cure.",
        },
    }
    groups = group_lines_for_customer(quote, _CATS)
    by_id = {g["category_id"]: g for g in groups}
    assert by_id["svc-pool"]["description"] == "Includes weekly chemistry balance."
    assert by_id["svc-tile"]["description"] == "Wet-sealing after cure."


def test_missing_descriptions_render_as_empty_string():
    quote = {
        "line_items": [_line("Chlorine treatment", 1, 60, "svc-pool")],
    }
    groups = group_lines_for_customer(quote, _CATS)
    assert groups[0]["description"] == ""


def test_long_description_never_leaks_into_grouped_rows():
    """K71 long_description is INTERNAL only — this is the contract lock."""
    secret = "INTERNAL notes only — do not show customer"
    quote = {
        "line_items": [
            _line("Chlorine treatment", 1, 60, "svc-pool",
                  long_description=secret),
        ],
    }
    groups = group_lines_for_customer(quote, _CATS)
    for row in groups:
        for value in row.values():
            assert secret not in str(value), (
                "long_description must NEVER surface on customer-facing "
                "grouped rows"
            )


def test_deleted_service_category_falls_back_to_id_label():
    quote = {
        "line_items": [_line("Legacy service", 1, 100, "svc-ghost")],
    }
    groups = group_lines_for_customer(quote, _CATS)  # svc-ghost not in cats
    assert groups[0]["category_id"] == "svc-ghost"
    assert groups[0]["label"] == "svc-ghost"  # id fallback


def test_empty_line_items_returns_empty_group_list():
    quote = {"line_items": []}
    assert group_lines_for_customer(quote, _CATS) == []


def test_currency_carried_from_quote_doc():
    quote = {
        "line_items": [_line("Service", 1, 50, "svc-pool")],
        "currency": "CAD",
    }
    groups = group_lines_for_customer(quote, _CATS)
    assert groups[0]["currency"] == "CAD"


def test_currency_defaults_to_usd_when_missing():
    quote = {"line_items": [_line("Service", 1, 50, "svc-pool")]}
    groups = group_lines_for_customer(quote, _CATS)
    assert groups[0]["currency"] == "USD"


# ═════════════════════════════════════════════════════════════════════
# build_customer_view_payload wrapper — preserves totals footer alongside
# the grouped rows.
# ═════════════════════════════════════════════════════════════════════
def test_build_payload_preserves_doc_level_totals():
    quote = {
        "customer_group_display": True,
        "line_items": [
            _line("A", 1, 60, "svc-pool"),
            _line("B", 1, 200, "svc-tile"),
        ],
        "subtotal": 260.0, "tax": 22.75, "total": 282.75,
        "discount_amount": 0.0, "amount_paid": 0.0,
    }
    payload = build_customer_view_payload(quote, _CATS)
    assert payload["customer_group_display"] is True
    assert payload["grouped_subtotal"] == 260.0
    assert payload["subtotal"] == 260.0
    assert payload["tax"] == 22.75
    assert payload["total"] == 282.75
    assert payload["amount_paid"] == 0.0
    assert len(payload["groups"]) == 2
