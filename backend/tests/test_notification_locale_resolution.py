"""Phase D5 · Feb-2026 — locale resolution priority chain."""
from __future__ import annotations

from services.i18n_notifications import resolve_recipient_locale


def test_customer_locale_wins_over_tenant_default():
    loc = resolve_recipient_locale(
        customer={"locale": "es"},
        tenant={"default_locale": "fr"},
        audience="customer",
    )
    assert loc == "es"


def test_customer_no_locale_falls_back_to_tenant_default():
    loc = resolve_recipient_locale(
        customer={"locale": None},
        tenant={"default_locale": "fr"},
        audience="customer",
    )
    assert loc == "fr"


def test_no_locale_anywhere_falls_back_to_en():
    loc = resolve_recipient_locale(
        customer={}, tenant={}, audience="customer",
    )
    assert loc == "en"


def test_tech_audience_reads_user_locale_over_tenant():
    loc = resolve_recipient_locale(
        customer={"locale": "es"},   # tech notifications ignore customer.locale
        tenant={"default_locale": "fr"},
        user={"locale": "es"},
        audience="tech",
    )
    assert loc == "es"


def test_tech_audience_no_user_locale_uses_tenant():
    loc = resolve_recipient_locale(
        tenant={"default_locale": "fr"},
        user={},
        audience="tech",
    )
    assert loc == "fr"


def test_admin_audience_always_english_regardless_of_signals():
    # Admin notifications stay English — locked D5 product decision.
    for signals in [
        {"customer": {"locale": "es"}, "tenant": {"default_locale": "fr"},
         "user": {"locale": "es"}},
        {"customer": {"locale": "fr"}, "tenant": {"default_locale": "fr"}},
        {"user": {"locale": "es"}},
    ]:
        assert resolve_recipient_locale(audience="admin", **signals) == "en"


def test_bcp47_region_suffix_is_trimmed():
    # es-MX and fr_CA both normalise to their base language.
    assert resolve_recipient_locale(
        customer={"locale": "es-MX"}, audience="customer",
    ) == "es"
    assert resolve_recipient_locale(
        customer={"locale": "fr_CA"}, audience="customer",
    ) == "fr"


def test_unknown_locale_normalises_to_en():
    assert resolve_recipient_locale(
        customer={"locale": "de"}, audience="customer",
    ) == "en"
