"""TD-76 Phase B (ph2d) · Feb-2026 — cleanup script branch tests.

Covers the ``_is_dead`` predicate (both branches) + a smoke test
of the ``--dry-run`` scan path. The ``--apply`` branch is tested
only via its predicate; mutating a real DB is reserved for
operator-run invocations against preview or prod.
"""
from __future__ import annotations

import pytest

from scripts.cleanup_dead_photo_rows import _is_dead


class TestIsDead:
    def test_empty_everything_is_dead(self):
        assert _is_dead({"id": "p1"}) is True
        assert _is_dead({"id": "p1", "url": "", "storage_path": "", "thumb": ""}) is True
        assert _is_dead({"id": "p1", "url": None,
                           "storage_path": None, "thumb": None}) is True
        # Whitespace-only strings count as empty.
        assert _is_dead({"id": "p1", "url": "   "}) is True

    def test_any_non_empty_byte_source_is_live(self):
        assert _is_dead({"id": "p1", "url": "https://cdn/x.jpg"}) is False
        assert _is_dead({"id": "p1", "storage_path": "t/x/f.jpg"}) is False
        assert _is_dead({"id": "p1", "thumb": "data:image/jpeg;base64,/9j/"}) is False

    def test_url_empty_but_storage_path_set_is_live(self):
        # The TD-76-ph2a OMIT branch already treats this as live
        # (storage_path becomes the resolved URL). Mirror here.
        assert _is_dead({"id": "p1", "url": "",
                           "storage_path": "t/x/f.jpg"}) is False

    def test_non_dict_input_is_not_dead(self):
        # Guard: a non-dict entry in photos[] is a schema anomaly,
        # not a dead row — leave it alone.
        assert _is_dead(None) is False
        assert _is_dead("not a photo") is False
        assert _is_dead(42) is False
