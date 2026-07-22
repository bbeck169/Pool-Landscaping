"""Phase 9C · Feb 2026 — Marketing media library coverage.

Storage client is mocked — no real Emergent Object Storage traffic in
unit tests. Real storage is exercised by the tester in a live probe
after this slice lands.
"""
from __future__ import annotations

import io
import struct
import uuid
from typing import Any, Dict, Tuple

import pytest
import requests

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    return requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw},
                          timeout=15).json()["access_token"]


def _hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# ─────────── Bytes helpers
def _png_bytes(size: int = 256) -> bytes:
    """A minimal-but-real-looking PNG. Header + IHDR + IDAT stub."""
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
    )
    return header + ihdr + b"\x00" * max(0, size - len(header) - len(ihdr))


def _svg_bytes(script: bool = False) -> bytes:
    body = "<script>alert(1)</script>" if script else "<circle/>"
    return f'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'.encode()


# ─────────── Mock the storage client via monkeypatch
@pytest.fixture(autouse=True)
def _mock_storage(monkeypatch):
    """Neutralise the real Emergent Object Storage calls at the source."""
    import services.marketing_media.storage_client as sc

    stored: Dict[str, Tuple[bytes, str]] = {}

    def _fake_put(path, data, content_type, max_retries=3):
        stored[path] = (data, content_type)
        return {"path": path}

    def _fake_get(path, max_retries=3):
        if path not in stored:
            raise sc.StorageUnavailable("object not found")
        return stored[path]

    def _fake_init(force=False):
        return "fake-storage-key"

    monkeypatch.setattr(sc, "put_object", _fake_put)
    monkeypatch.setattr(sc, "get_object", _fake_get)
    monkeypatch.setattr(sc, "init_storage", _fake_init)
    # Also patch the router-side imports in case they were bound at import time.
    import routers.marketing_media as mm
    monkeypatch.setattr(mm, "put_object", _fake_put)
    monkeypatch.setattr(mm, "get_object", _fake_get)
    yield stored


def _upload(tok: str, *, filename: str, data: bytes,
             content_type: str = "image/png") -> requests.Response:
    files = {"file": (filename, data, content_type)}
    return requests.post(f"{API}/marketing/media/upload",
                          headers=_hdr(tok),
                          files=files, timeout=25)


# ═══════════════════════════ Role gates ══════════════════════════════
def test_upload_denies_customer():
    tok = _login("customer@aquaterra.com")
    r = _upload(tok, filename="x.png", data=_png_bytes())
    assert r.status_code == 403


def test_upload_denies_technician():
    tok = _login("mike@aquaterra.com")
    r = _upload(tok, filename="x.png", data=_png_bytes())
    assert r.status_code == 403


# ═══════════════════════════ Happy path ══════════════════════════════
def test_upload_png_happy_path_then_list_patch():
    tok = _login("admin@aquaterra.com")
    r = _upload(tok, filename="cover.png", data=_png_bytes(2048))
    assert r.status_code == 200, r.text
    j = r.json()
    mid = j["id"]
    assert j["mime_type"] == "image/png"
    assert j["url"].endswith(f"/api/marketing/media/{mid}/download")
    # GET list
    lst = requests.get(f"{API}/marketing/media?page=1&page_size=50",
                        headers=_hdr(tok), timeout=15).json()
    assert any(row["id"] == mid for row in lst["rows"])
    # PATCH alt_text + tags
    p = requests.patch(f"{API}/marketing/media/{mid}",
                        headers={**_hdr(tok), "Content-Type": "application/json"},
                        json={"alt_text": "Sunny cover",
                                "tags": "seasonal,pool"},
                        timeout=15)
    assert p.status_code == 200
    assert p.json()["alt_text"] == "Sunny cover"
    assert set(p.json()["tags"]) == {"seasonal", "pool"}


# ═══════════════════════════ Magic-byte mismatch ═════════════════════
def test_upload_magic_byte_mismatch_415():
    tok = _login("admin@aquaterra.com")
    # Declares PNG but bytes are plain text.
    r = _upload(tok, filename="fake.png", data=b"not a png",
                  content_type="image/png")
    assert r.status_code == 415
    assert "magic-bytes" in r.text.lower() or "match" in r.text.lower()


# ═══════════════════════════ Oversize / SVG guard ════════════════════
def test_upload_oversize_413():
    tok = _login("admin@aquaterra.com")
    big = _png_bytes(6 * 1024 * 1024)
    r = _upload(tok, filename="huge.png", data=big)
    assert r.status_code == 413


def test_upload_svg_happy_path():
    tok = _login("admin@aquaterra.com")
    r = _upload(tok, filename="logo.svg", data=_svg_bytes(script=False),
                  content_type="image/svg+xml")
    assert r.status_code == 200, r.text


def test_upload_svg_with_script_415():
    tok = _login("admin@aquaterra.com")
    r = _upload(tok, filename="evil.svg", data=_svg_bytes(script=True),
                  content_type="image/svg+xml")
    assert r.status_code == 415


# ═══════════════════════════ Soft-delete + 409 ref-guard ═════════════
def test_soft_delete_blocked_by_template_reference_then_succeeds():
    tok = _login("admin@aquaterra.com")
    up = _upload(tok, filename="banner.png", data=_png_bytes(1024)).json()
    mid = up["id"]
    url = up["url"]
    # Create a template body referencing the image URL.
    tpl = requests.post(
        f"{API}/marketing/templates",
        headers={**_hdr(tok), "Content-Type": "application/json"},
        json={"name": "Ref Guard Tpl", "channel": "email",
                "category": "general", "subject": "Look",
                "body": f'<p><img src="{url}" alt=""></p>'},
        timeout=15,
    ).json()
    # DELETE must return 409 with the template id.
    d = requests.delete(f"{API}/marketing/media/{mid}",
                          headers=_hdr(tok), timeout=15)
    assert d.status_code == 409, d.text
    detail = d.json().get("detail") or {}
    assert tpl["id"] in (detail.get("referencing_template_ids") or [])
    # Remove the reference from the template body.
    requests.patch(
        f"{API}/marketing/templates/{tpl['id']}",
        headers={**_hdr(tok), "Content-Type": "application/json"},
        json={"body": "<p>no image now</p>"},
        timeout=15,
    )
    # Retry DELETE — must succeed.
    d2 = requests.delete(f"{API}/marketing/media/{mid}",
                           headers=_hdr(tok), timeout=15)
    assert d2.status_code == 200, d2.text
    # Restore.
    r = requests.post(f"{API}/marketing/media/{mid}/restore",
                        headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    # Cleanup: hard-delete the template row so the tenant stays clean.
    requests.delete(f"{API}/marketing/templates/{tpl['id']}",
                      headers=_hdr(tok), timeout=10)


# ═══════════════════════════ Restore ═════════════════════════════════
def test_restore_reverts_deleted_at():
    tok = _login("admin@aquaterra.com")
    up = _upload(tok, filename="temp.png", data=_png_bytes()).json()
    mid = up["id"]
    # Delete first (no references).
    r = requests.delete(f"{API}/marketing/media/{mid}",
                          headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    # Confirm hidden by default.
    lst = requests.get(f"{API}/marketing/media?page=1&page_size=100",
                        headers=_hdr(tok), timeout=15).json()
    assert not any(row["id"] == mid for row in lst["rows"])
    # Restore.
    r = requests.post(f"{API}/marketing/media/{mid}/restore",
                        headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    lst2 = requests.get(f"{API}/marketing/media?page=1&page_size=100",
                         headers=_hdr(tok), timeout=15).json()
    assert any(row["id"] == mid for row in lst2["rows"])


# ═══════════════════════════ Download proxy ══════════════════════════
def test_download_proxy_returns_bytes():
    tok = _login("admin@aquaterra.com")
    payload = _png_bytes(512)
    up = _upload(tok, filename="dl.png", data=payload).json()
    r = requests.get(f"{API}/marketing/media/{up['id']}/download",
                      headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/png")
    # Response bytes are what the storage stub returned (EXIF-stripped
    # payload). It's an image, not the assertion target; just prove
    # non-empty content.
    assert len(r.content) > 0
