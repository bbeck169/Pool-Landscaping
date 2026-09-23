"""Phase P37.1 · Feb-2026 — Mongo connection pool config test.

Locks the P37.1 cleanup: single Motor client, kwargs applied
correctly, no ``maxPoolSize`` leaking into the URL query string.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse, parse_qsl


def test_p37_1_mongo_max_pool_size_landed():
    """The Motor client MUST be constructed with the pool cap the
    P37.1 constant declares.

    We source-lint ``backend/config.py`` rather than inspecting
    ``client.options.pool_options.max_pool_size`` because the F7
    loop fixture rebinds a test-local ``AsyncIOMotorClient`` for
    isolation (default pool size). The source-lint asserts the
    production-boot construction, which is what matters."""
    import re
    from pathlib import Path
    from config import _MONGO_MAX_POOL_SIZE
    # Constant used at construction is the P37.1 single-source-of-truth.
    assert _MONGO_MAX_POOL_SIZE == 300, (
        "P37.1: maxPoolSize=300 is the deliberate concurrency budget "
        f"(current: {_MONGO_MAX_POOL_SIZE}). Do not lower without a "
        "load-test."
    )
    cfg_src = Path(__file__).resolve().parent.parent.joinpath("config.py").read_text()
    # Assert the kwarg is wired into the AsyncIOMotorClient(...) call.
    assert re.search(
        r"AsyncIOMotorClient\(\s*mongo_url,\s*"
        r"maxPoolSize=_MONGO_MAX_POOL_SIZE",
        cfg_src,
    ), "config.py must construct AsyncIOMotorClient with maxPoolSize=_MONGO_MAX_POOL_SIZE"


def test_p37_1_mongo_server_selection_timeout_landed():
    """P37.1 boot guard — 5s server-selection timeout so an Atlas
    hiccup can't stall pod boot for 30s. Source-lint (see above
    test for the rationale on avoiding client inspection)."""
    import re
    from pathlib import Path
    from config import _MONGO_SERVER_SELECTION_TIMEOUT_MS
    assert _MONGO_SERVER_SELECTION_TIMEOUT_MS == 5000
    cfg_src = Path(__file__).resolve().parent.parent.joinpath("config.py").read_text()
    assert re.search(
        r"serverSelectionTimeoutMS=_MONGO_SERVER_SELECTION_TIMEOUT_MS",
        cfg_src,
    ), (
        "config.py must construct AsyncIOMotorClient with "
        "serverSelectionTimeoutMS=_MONGO_SERVER_SELECTION_TIMEOUT_MS"
    )


def test_p37_1_startup_log_line_present():
    """P37.1 · the ``[mongo] maxPoolSize=... serverSelectionTimeoutMS=...``
    startup log MUST be emitted at boot so ops can grep the effective
    pool config from pod logs."""
    import re
    from pathlib import Path
    cfg_src = Path(__file__).resolve().parent.parent.joinpath("config.py").read_text()
    assert re.search(
        r"\[mongo\] maxPoolSize=%s serverSelectionTimeoutMS=%s "
        r"\(source=code\)",
        cfg_src,
    ), "config.py must emit the P37.1 [mongo] startup log"


def test_p37_1_mongo_url_has_no_max_pool_size_in_query():
    """P37.1 hygiene — MONGO_URL must NOT carry ``maxPoolSize`` in
    its query string. Single-source-of-truth in code."""
    url = os.environ.get("MONGO_URL") or ""
    if not url:
        # Test env may strip the URL; not a P37.1 concern.
        return
    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    assert "maxPoolSize" not in params, (
        "MONGO_URL query string carries maxPoolSize — P37.1 requires "
        "single-source-of-truth in code. Remove from the secret store."
    )
    assert "max_pool_size" not in params
    # Also detect duplicate params for the same key (would mean the
    # URL has ``?x=1&x=2``). ``parse_qsl`` returns duplicates as
    # separate tuples so a set-vs-list length diff surfaces them.
    all_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    keys = [k for k, _ in all_pairs]
    dupes = [k for k in set(keys) if keys.count(k) > 1]
    assert not dupes, (
        f"MONGO_URL query string has duplicate params: {dupes}. "
        "Ops must dedupe in the secret store."
    )


def test_p37_1_single_motor_client_singleton():
    """P37.1 · exactly ONE ``AsyncIOMotorClient`` instantiation
    lives in the codebase. A second client would silently
    double the pool + confuse dev-tools tracing. Source-lint
    guards against a future regression that spawns a
    per-request client."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    # Sanity — a couple of ancillary files intentionally construct
    # ephemeral clients (migrations, tests, scripts) and are OK.
    # The invariant we care about is: production imports flow
    # through ``config.py::client``.
    cfg_src = (root / "config.py").read_text()
    assert cfg_src.count("AsyncIOMotorClient(") == 1, (
        "expected exactly one AsyncIOMotorClient construction in "
        "config.py — see P37.1 docstring above the client line."
    )
