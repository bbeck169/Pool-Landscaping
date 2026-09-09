"""
Feb-2026 · Batch #4 · Logo ship — backend logo helper tests.

Direct tests against the ``get_tenant_logo_path`` / ``get_tenant_logo_url``
helpers in ``routers.invoice_viewer``. Byte-level assertions that the
resolver returns the new Pool & Landscaping of Vistancia default asset
and that PDF renderers can actually open + hash-match it.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path

import pytest

from routers.invoice_viewer import (
    _DEFAULT_LOGO_PATH,
    _DEFAULT_LOGO_URL,
    get_tenant_logo_path,
    get_tenant_logo_url,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOGO_FILE = (
    REPO_ROOT / "backend" / "static" / "logos"
    / "pool-landscaping-of-vistancia.png"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def test_default_logo_asset_exists_on_disk():
    """The Pool & Landscaping of Vistancia default logo must be
    checked into the backend static tree so the PDF renderers can
    ``open()`` it without a network round-trip."""
    assert DEFAULT_LOGO_FILE.exists(), (
        f"Default logo missing at {DEFAULT_LOGO_FILE}. "
        "The Batch #4 logo ship depends on this asset."
    )
    assert DEFAULT_LOGO_FILE.stat().st_size > 10_000, (
        "Default logo suspiciously small — did the download truncate?"
    )


def test_default_constants_point_at_the_new_asset():
    """Guard against a future rename accidentally regressing back to
    the legacy ``/logo-full.png``."""
    assert _DEFAULT_LOGO_URL == "/logos/pool-landscaping-of-vistancia@1x.png"
    assert _DEFAULT_LOGO_PATH.endswith(
        os.path.join("static", "logos", "pool-landscaping-of-vistancia.png"),
    )


def test_get_tenant_logo_path_no_override_returns_default_and_file_is_readable():
    """Empty tenant → default path returned + the file opens with the
    same SHA256 as the ground-truth asset on disk (byte-level
    verification that PDF renderers embed the intended image)."""
    path = get_tenant_logo_path({})
    assert path is not None
    assert Path(path).exists()
    assert _sha256(Path(path)) == _sha256(DEFAULT_LOGO_FILE)


def test_get_tenant_logo_path_tenant_override_wins(tmp_path):
    fake_logo = tmp_path / "tenant-x.png"
    # Any content is fine — helper only checks existence.
    fake_logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"stub")
    tenant = {"settings": {"business_card": {
        "logo_local_path": str(fake_logo),
    }}}
    assert get_tenant_logo_path(tenant) == str(fake_logo)


def test_get_tenant_logo_path_missing_override_falls_back_to_default(tmp_path):
    tenant = {"settings": {"business_card": {
        "logo_local_path": str(tmp_path / "does-not-exist.png"),
    }}}
    path = get_tenant_logo_path(tenant)
    assert path is not None
    assert Path(path).name == "pool-landscaping-of-vistancia.png"


def test_get_tenant_logo_url_default_and_override():
    assert get_tenant_logo_url({}) == _DEFAULT_LOGO_URL
    assert get_tenant_logo_url({"logo_url": "https://cdn.example/x.png"}) \
        == "https://cdn.example/x.png"


def test_pdf_renderer_can_open_the_default_logo():
    """Smoke test the ReportLab entry point that the invoice / estimate
    PDF routers use. If this raises, the doc PDFs would silently drop
    the logo (see the ``except`` branch in the renderers)."""
    from reportlab.platypus import Image
    from reportlab.lib.units import inch
    im = Image(str(DEFAULT_LOGO_FILE),
                width=2.4 * inch, height=0.9 * inch,
                kind="proportional")
    # ReportLab reads dimensions lazily on wrap — force it.
    w, h = im.wrap(6 * inch, 2 * inch)
    assert w > 0 and h > 0
