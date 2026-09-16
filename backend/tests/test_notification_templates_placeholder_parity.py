"""Phase D5 · Feb-2026 — placeholder-parity drift guard across locales.

For every ``en/*`` notification template file, assert:
1. The corresponding ``es/`` and ``fr/`` files exist.
2. The set of ``{placeholder}`` tokens is IDENTICAL across all three.
3. No SMS translation exceeds 320 chars (2 GSM-7 segments) — flag any
   proactive tightening opportunity to the maintainer.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.i18n_notifications import (
    SUPPORTED_LOCALES,
    SMS_GSM7_SEGMENT_CHARS,
    extract_placeholders,
    sms_segment_count,
)

_ROOT = Path(__file__).resolve().parent.parent / "services" / "notification_templates"


def _english_files():
    return sorted((_ROOT / "en").glob("*"))


@pytest.mark.parametrize("en_file", _english_files(),
                            ids=lambda p: p.name)
def test_es_and_fr_counterparts_exist_and_placeholders_match(en_file: Path):
    if en_file.name.startswith("README"):
        pytest.skip("READMEs are docs, not templates")
    if en_file.is_dir():
        pytest.skip("dir")
    relative = en_file.name  # e.g. ``completion_sms.sms.txt``
    en_text = en_file.read_text(encoding="utf-8")
    en_tokens = extract_placeholders(en_text)
    for loc in sorted(SUPPORTED_LOCALES - {"en"}):
        counterpart = _ROOT / loc / relative
        assert counterpart.exists(), (
            f"[phase-d5-parity] missing {loc}/{relative} — every en/ "
            f"template must have an es/ and fr/ counterpart"
        )
        loc_tokens = extract_placeholders(counterpart.read_text(encoding="utf-8"))
        assert loc_tokens == en_tokens, (
            f"[phase-d5-parity] placeholder drift in {loc}/{relative}: "
            f"missing={en_tokens - loc_tokens} extra={loc_tokens - en_tokens} — "
            "translators MUST preserve every {placeholder} verbatim"
        )


def test_no_sms_translation_exceeds_two_segments():
    """Every translated SMS body under 320 chars (2 segments). If a
    real string exceeds this, tighten the copy proactively.

    Passes an example merge-var context so the length reflects a
    realistic rendered body, not the template with tokens still in.
    """
    ctx = {
        "first_name": "Alexander",
        "job_title": "Weekly pool cleaning",
        "business_name": "Pool & Landscaping of Vistancia",
        "portal_link": "https://app.plofv.com/portal/jobs/abcd1234efgh5678ijkl9012mnop3456",
        "customer_first_name": "Alexander",
        "add_card_link": "https://app.plofv.com/portal/add-card?token=abcd.ef.ghij.klmn",
    }
    for sms_path in sorted(_ROOT.glob("*/*.sms.txt")):
        raw = sms_path.read_text(encoding="utf-8").rstrip("\n")
        body = raw.format(**{
            k: v for k, v in ctx.items() if "{" + k + "}" in raw
        })
        segs = sms_segment_count(body)
        assert segs <= 2, (
            f"[phase-d5-sms-length] {sms_path.relative_to(_ROOT)}: "
            f"{len(body)} chars → {segs} segments (exceeds 320 char / "
            f"2-segment budget) — tighten the copy"
        )
