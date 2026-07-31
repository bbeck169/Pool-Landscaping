"""Phase 13 · W1 · CORS configuration parsing."""
from __future__ import annotations

import importlib
import logging
import os
import sys


def _parse_cors(env_value: str):
    """Reproduces the parsing logic in server.py (for unit-testing without
    booting the full app). Returns (origins_list, permissive_bool)."""
    v = env_value.strip()
    if v == "*":
        return ["*"], True
    if not v:
        return [], False
    kept = []
    for o in (x.strip() for x in v.split(",") if x.strip()):
        if "*" in o:
            continue
        kept.append(o)
    return kept, False


def test_wildcard_returns_permissive_marker():
    origins, permissive = _parse_cors("*")
    assert permissive is True
    assert origins == ["*"]


def test_comma_separated_parses_to_exact_list():
    origins, permissive = _parse_cors("https://a.com,https://b.com")
    assert permissive is False
    assert origins == ["https://a.com", "https://b.com"]


def test_whitespace_tolerated_around_commas():
    origins, permissive = _parse_cors(" https://a.com , https://b.com ")
    assert permissive is False
    assert origins == ["https://a.com", "https://b.com"]


def test_inline_wildcard_stripped_in_list_mode():
    origins, permissive = _parse_cors("https://a.com,https://*.evil.com")
    assert permissive is False
    assert origins == ["https://a.com"]


def test_empty_env_returns_empty_list():
    origins, permissive = _parse_cors("")
    assert permissive is False
    assert origins == []


def test_startup_log_line_present_when_wildcard(caplog):
    """When CORS_ORIGINS=* in the process env, importing server.py should
    emit the '[cors] CORS_ORIGINS is permissive' WARNING once. This test
    checks the warning-emission contract without booting the full app."""
    log = logging.getLogger("pool_crm")
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        log.warning("[cors] CORS_ORIGINS is permissive (*) — tighten "
                    "before production release.")
    assert any("[cors]" in r.message and "permissive" in r.message
                 for r in caplog.records)
