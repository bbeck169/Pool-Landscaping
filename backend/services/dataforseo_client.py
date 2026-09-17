"""Feb-2026 · Phase 23-A — DataForSEO client shim.

Thin async wrapper around DataForSEO's HTTP Basic-auth JSON API.  Only
implements the two endpoints we use in v1:

* ``serp/google/organic/live/regular`` — one SERP for a given
  (keyword, coordinate) pair.
* ``appendix/user_data``            — account credits + limits.

Every helper returns ``(status_int, payload_dict_or_None, error_str_or_None)``
so callers can log/toast without teaching them httpx idioms.  A ``402``
means DataForSEO says the account is out of credits — we surface a
distinct message so the UI can prompt the admin to top up.
"""
from __future__ import annotations

import os
import base64
import json
from typing import Any, Dict, Optional, Tuple

import httpx

from config import logger

_BASE = "https://api.dataforseo.com/v3"


def _creds() -> Optional[Tuple[str, str]]:
    login = os.environ.get("DATAFORSEO_LOGIN")
    pw = os.environ.get("DATAFORSEO_PASSWORD")
    if not (login and pw):
        return None
    return login, pw


def get_credentials_or_none() -> Optional[Tuple[str, str]]:
    """Public alias of ``_creds`` — callers outside this module use
    this to gate DFS-dependent code paths without probing env vars
    directly."""
    return _creds()


def get_credentials_for_tenant(
    tenant_doc: Optional[Dict[str, Any]],
) -> Optional[Tuple[str, str]]:
    """Sep-2026 · Per-tenant BYO DFS credentials.

    Reads ``tenant.settings.integrations.dataforseo.{login_encrypted,
    password_encrypted}`` and decrypts with the module-level Fernet
    helper. Returns ``None`` on:
      • Missing tenant doc / settings path
      • Encryption key not configured (feature disabled)
      • Tampered ciphertext
      • Empty/invalid decrypted plaintext

    Callers MUST fall through to :func:`get_credentials_or_none`
    (global env) on ``None`` — see :func:`get_effective_credentials`.
    """
    if not tenant_doc:
        return None
    integ = ((tenant_doc.get("settings") or {}).get("integrations") or {}) \
        .get("dataforseo") or {}
    login_ct = integ.get("login_encrypted")
    pw_ct = integ.get("password_encrypted")
    if not (login_ct and pw_ct):
        return None
    from services.tenant_secrets_crypto import decrypt_tenant_secret
    login = decrypt_tenant_secret(login_ct)
    pw = decrypt_tenant_secret(pw_ct)
    if not (login and pw):
        return None
    return login, pw


def get_effective_credentials(
    tenant_doc: Optional[Dict[str, Any]],
) -> Optional[Tuple[str, str, str]]:
    """Sep-2026 · Priority resolver: **tenant → global → None**.

    Returns a 3-tuple ``(login, password, source)`` where ``source``
    is ``"tenant"`` (BYO creds) or ``"global"`` (platform default).
    Callers use ``source`` for cost telemetry — tenant credit calls
    are billed to the tenant's DFS account; global credit calls
    burn the platform's shared account.
    """
    t = get_credentials_for_tenant(tenant_doc)
    if t:
        return (t[0], t[1], "tenant")
    g = get_credentials_or_none()
    if g:
        return (g[0], g[1], "global")
    return None


def log_auth_config() -> None:
    """Called from server boot so a truthy line appears in the logs."""
    c = _creds()
    if c:
        logger.info(f"[dataforseo] auth configured — login={c[0]}")
    else:
        logger.warning("[dataforseo] no credentials in env (skipping rank tracker)")


async def _post(path: str, tasks: list[Dict[str, Any]],
                 *, creds_override: Optional[Tuple[str, str]] = None,
                 ) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    # Sep-2026 · Per-tenant BYO creds. When ``creds_override`` is
    # provided, use it (billed to the tenant's DFS account); else
    # fall back to the platform global env creds.
    c = creds_override or _creds()
    if not c:
        return 0, None, "no_credentials"
    login, pw = c
    b64 = base64.b64encode(f"{login}:{pw}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/json",
    }
    url = f"{_BASE}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(url, headers=headers, json=tasks)
    except httpx.RequestError as e:
        logger.warning(f"[dataforseo] transport error: {e}")
        return 0, None, f"transport_error: {e}"

    if r.status_code == 401:
        return 401, None, "auth_failed"
    if r.status_code == 402:
        return 402, None, "out_of_credits"
    try:
        body = r.json()
    except json.JSONDecodeError:
        return r.status_code, None, f"non_json_body: {r.text[:200]}"
    # DataForSEO returns a top-level 20000 status_code for full success on
    # the outer envelope even when individual task rows fail. We surface
    # anything else as an error string. 40104 = unverified account —
    # bucket it into a distinct short string so callers can short-circuit
    # (retrying won't help until the admin verifies the account).
    api_sc = body.get("status_code")
    if api_sc == 40104:
        return r.status_code, body, "account_unverified"
    if api_sc == 40100:
        return r.status_code, body, "auth_failed"
    if api_sc not in (20000, 20100):
        return r.status_code, body, f"api_status_code={api_sc}: {body.get('status_message')}"
    return r.status_code, body, None


async def serp_google_organic_live(
    keyword: str,
    lat: float,
    lng: float,
    *,
    language_code: str = "en",
    depth: int = 100,
    creds_override: Optional[Tuple[str, str]] = None,
) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    """Fetch the live top-``depth`` Google organic SERP for a coord.

    ``creds_override`` (Sep-2026) — pass tenant BYO creds tuple to
    bill THIS call to the tenant's DFS account instead of the
    platform global. Callers get the tuple from
    :func:`get_effective_credentials` and forward it here.
    """
    task = [{
        "keyword": keyword,
        "language_code": language_code,
        "location_coordinate": f"{lat:.6f},{lng:.6f},10",  # 10-mile radius per DFS spec
        "device": "desktop",
        "depth": depth,
    }]
    return await _post("serp/google/organic/live/regular", task,
                          creds_override=creds_override)


async def user_credits() -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    """Account balance + credit stats. DataForSEO expects a GET here but
    accepts POST too; we use POST to stay consistent with the SERP call.
    """
    c = _creds()
    if not c:
        return 0, None, "no_credentials"
    login, pw = c
    b64 = base64.b64encode(f"{login}:{pw}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {b64}"}
    url = f"{_BASE}/appendix/user_data"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers)
    except httpx.RequestError as e:
        return 0, None, f"transport_error: {e}"
    if r.status_code == 401:
        return 401, None, "auth_failed"
    try:
        body = r.json()
    except json.JSONDecodeError:
        return r.status_code, None, f"non_json_body"
    return r.status_code, body, None


def parse_serp_ranks(
    body: Optional[Dict[str, Any]],
    target_domains: list[str],
) -> Dict[str, Optional[int]]:
    """Return ``{domain: rank_or_None}`` for each provided target domain.

    Uses the first task in the response payload. ``rank`` is 1-based
    matching the surfaced SERP position, ``None`` if the domain is
    absent from the returned items.
    """
    detailed = parse_serp_ranks_detailed(body, target_domains)
    return {d: (detailed[d] or {}).get("rank") for d in target_domains}


def parse_serp_ranks_detailed(
    body: Optional[Dict[str, Any]],
    target_domains: list[str],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Same as ``parse_serp_ranks`` but also returns ``url`` and ``title``
    of the matched SERP item so callers can persist ``url_found`` for
    audit / debugging.
    """
    out: Dict[str, Optional[Dict[str, Any]]] = {d: None for d in target_domains}
    if not body:
        return out
    tasks = body.get("tasks") or []
    if not tasks:
        return out
    result = tasks[0].get("result") or []
    if not result:
        return out
    items = result[0].get("items") or []
    for item in items:
        rank = item.get("rank_absolute") or item.get("rank_group")
        url = (item.get("url") or "").lower()
        domain = (item.get("domain") or "").lower()
        if not rank or not (url or domain):
            continue
        for target in target_domains:
            t = target.lower().replace("https://", "").replace("http://", "").rstrip("/")
            if t and (t in domain or t in url) and out.get(target) is None:
                out[target] = {
                    "rank": int(rank),
                    "url": item.get("url"),
                    "title": item.get("title"),
                    "domain": item.get("domain"),
                }
    return out
