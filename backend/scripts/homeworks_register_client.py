#!/usr/bin/env python3
"""Feb-2026 · Homeworks OAuth Dynamic Client Registration (RFC 7591).

One-shot admin script. Registers ``AquaTerra CRM`` with the Homeworks
Authorization Server, prints the returned ``client_id``, and appends
``HOMEWORKS_CLIENT_ID=<value>`` to ``backend/.env``.

Idempotent — if ``HOMEWORKS_CLIENT_ID`` is already set (env or .env),
skips the POST and prints "already registered".

Usage::

    cd /app/backend && python3 -m scripts.homeworks_register_client
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv


REGISTRATION_ENDPOINT = "https://api.home.works/oauth/register"
CLIENT_NAME = "AquaTerra CRM"
SCOPE = "openid company"
GRANT_TYPES = ["authorization_code", "refresh_token"]
RESPONSE_TYPES = ["code"]
TOKEN_ENDPOINT_AUTH_METHOD = "none"  # public client + PKCE

DEFAULT_PROD_HOST = "app.plofv.com"

_ENV_PATH = Path("/app/backend/.env")


def _load_env() -> None:
    load_dotenv(_ENV_PATH)


def _existing_client_id() -> Optional[str]:
    v = (os.environ.get("HOMEWORKS_CLIENT_ID") or "").strip()
    return v or None


def _prod_host() -> str:
    return (os.environ.get("HOMEWORKS_PROD_HOST") or DEFAULT_PROD_HOST).strip()


def _preview_backend_url() -> str:
    """Pull ``REACT_APP_BACKEND_URL`` from the frontend .env."""
    try:
        with open("/app/frontend/.env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def build_redirect_uris() -> List[str]:
    prod_host = _prod_host()
    preview = _preview_backend_url()
    uris = [
        f"https://{prod_host}/api/integrations/homeworks/oauth/callback",
    ]
    if preview and preview.startswith("http"):
        uris.append(f"{preview.rstrip('/')}/api/integrations/homeworks/oauth/callback")
    uris.append("http://localhost:3000/api/integrations/homeworks/oauth/callback")
    # De-dupe preserving order — the AS rejects duplicates.
    seen = set()
    out: List[str] = []
    for u in uris:
        if u not in seen:
            out.append(u); seen.add(u)
    return out


def _append_env(key: str, value: str) -> None:
    """Append ``KEY=value`` to ``backend/.env``.

    Refuses to overwrite an existing key — the caller is expected to
    have checked ``_existing_client_id()`` first. If the file is
    missing (unlikely in this pod), creates it.
    """
    # Load existing lines to check for the key (in case load_dotenv
    # missed a comment-only or blank-only file).
    lines: List[str] = []
    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    for line in lines:
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            raise RuntimeError(
                f"{key} already present in {_ENV_PATH} — refusing to append",
            )
    with open(_ENV_PATH, "a", encoding="utf-8") as f:
        if lines and not (lines[-1] == "" or lines[-1].endswith("\n")):
            f.write("\n")
        f.write(f"{key}={value}\n")


def register(redirect_uris: List[str]) -> Dict[str, Any]:
    body = {
        "client_name": CLIENT_NAME,
        "redirect_uris": redirect_uris,
        "grant_types": GRANT_TYPES,
        "response_types": RESPONSE_TYPES,
        "token_endpoint_auth_method": TOKEN_ENDPOINT_AUTH_METHOD,
        "scope": SCOPE,
    }
    print(f"→ POST {REGISTRATION_ENDPOINT}")
    print(f"  redirect_uris: {json.dumps(redirect_uris)}")
    r = httpx.post(
        REGISTRATION_ENDPOINT,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=20.0,
    )
    if r.status_code >= 400:
        print(f"✗ DCR failed HTTP {r.status_code}\n{r.text[:600]}")
        sys.exit(2)
    return r.json()


def main() -> int:
    _load_env()
    existing = _existing_client_id()
    if existing:
        print(f"already registered · HOMEWORKS_CLIENT_ID=…{existing[-4:]}")
        return 0
    uris = build_redirect_uris()
    payload = register(uris)
    cid = (payload.get("client_id") or "").strip()
    if not cid:
        print("✗ AS returned no client_id — dumping payload:")
        print(json.dumps(payload, indent=2)[:1000])
        return 3
    _append_env("HOMEWORKS_CLIENT_ID", cid)
    print(f"✓ registered · client_id=…{cid[-4:]} · appended to {_ENV_PATH}")
    print("Redirect URIs accepted by AS:")
    for u in payload.get("redirect_uris") or uris:
        print(f"  · {u}")
    # Reveal a couple of the more useful fields for the log without
    # leaking the client_id itself.
    for k in (
        "token_endpoint_auth_method", "grant_types", "response_types",
        "scope", "client_id_issued_at",
    ):
        if k in payload:
            print(f"  {k}: {payload[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
