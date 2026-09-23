"""Phase P39 · Feb-2026 — telematics integration tests.

Twenty scenarios per the P39 brief (13 from the original scope + 7
added for Change 1 poller + Change 2 rich mgmt table + backfill):

Provider registration + config encryption
  1.  test_register_telematics_kind_returns_both_providers
  2.  test_save_provider_config_encrypts_secrets

Signed URL minting + tenant token verification
  3.  test_webhook_url_endpoint_returns_signed_url
  4.  test_webhook_rejects_invalid_tenant_token_401

Mojio signature path
  5.  test_mojio_webhook_rejects_invalid_signature_401
  6.  test_mojio_webhook_accepts_valid_signature_200_persists_ping

Geotab shared-secret path
  7.  test_geotab_webhook_rejects_missing_shared_secret_401
  8.  test_geotab_webhook_accepts_matching_shared_secret_200

Idempotency + vehicle resolution
  9.  test_webhook_idempotency_duplicate_event_id_returns_duplicate_shape
  10. test_webhook_unmapped_vehicle_stores_ping_with_null_technician
  11. test_webhook_mapped_vehicle_stores_ping_with_technician_id

CRUD + unmapped list
  12. test_vehicle_links_crud_tenant_scoped
  13. test_unmapped_vehicles_endpoint_returns_last_30_days_null_tech_only

Change 2 · Rich mgmt table + backfill
  14. test_vehicle_links_stats_returns_last_seen_and_count
  15. test_create_link_with_backfill_updates_null_tech_pings
  16. test_create_link_without_backfill_leaves_pings_null

Change 1 · MyGeotab polling adapter
  17. test_geotab_poller_disabled_by_default
  18. test_geotab_poller_reads_devicestatusinfo_and_persists
  19. test_geotab_poller_dedup_on_repeated_dateTime
  20. test_geotab_poller_backoff_on_auth_error
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch, AsyncMock

import httpx
import pytest

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════
# Shared fixtures / helpers
# ═════════════════════════════════════════════════════════════════
os.environ.setdefault("TELEMATICS_URL_SIGNING_SECRET", "p39-test-signing-secret-32b")
os.environ.setdefault("SECRETS_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")


async def _wipe(db, tenant_ids: List[str], vehicle_ids: List[str] | None = None) -> None:
    await db.tenants.delete_many({"id": {"$in": tenant_ids}})
    await db.tenant_secrets.delete_many({"tenant_id": {"$in": tenant_ids}})
    await db.telematics_vehicle_links.delete_many({"tenant_id": {"$in": tenant_ids}})
    q: Dict[str, Any] = {"tenant_id": {"$in": tenant_ids}}
    if vehicle_ids:
        q["external_vehicle_id"] = {"$in": vehicle_ids}
    await db.gps_pings.delete_many(q)
    await db.users.delete_many({"tenant_id": {"$in": tenant_ids}})


async def _seed_tenant(db, tid: str, name: str = "p39-test") -> None:
    await db.tenants.insert_one({"id": tid, "name": name})


async def _seed_technician(db, tid: str, uid: str) -> None:
    await db.users.insert_one({
        "id": uid,
        "tenant_id": tid,
        "role": "technician",
        "name": f"tech-{uid}",
    })


async def _ensure_dedup_index(db) -> None:
    """Some F7 tests import ``scripts.ensure_indexes`` which creates
    the dedup index we rely on in the persist tests.  Do the same
    inline so this test module runs standalone."""
    from pymongo import IndexModel
    from pymongo.errors import OperationFailure
    try:
        await db.gps_pings.create_indexes([
            IndexModel(
                [("tenant_id", 1), ("external_vehicle_id", 1), ("captured_at", 1)],
                name="gps_pings_dedup_bg",
                unique=True,
                background=True,
                partialFilterExpression={
                    "external_vehicle_id": {"$type": "string"},
                },
            ),
        ])
    except OperationFailure:
        pass  # index already exists with same shape or slightly different name


async def _seed_provider_config(
    db,
    tid: str,
    *,
    provider_key: str,
    webhook_secret: str,
    account_id: str = "acct-x",
    api_key: str = "sk_p39_test",
    server_url: Optional[str] = None,
) -> None:
    """Save a telematics provider config through the real save path
    so the secret gets encrypted-at-rest and the webhook receiver's
    ``load_provider_config`` decrypts it symmetrically."""
    from services.telematics._helpers import save_provider_config
    from services.telematics import get_provider
    meta = get_provider(provider_key)
    config: Dict[str, Any] = {
        "api_key": api_key,
        "account_id": account_id,
        "webhook_secret": webhook_secret,
    }
    if server_url is not None:
        config["server_url"] = server_url
    await save_provider_config(
        tenant_id=tid,
        provider_key=provider_key,
        config=config,
        schema=meta.config_fields,
        primary_secret_field=meta.primary_secret_field,
        db=db,
    )


def _mint_url_token(tid: str, provider_short: str) -> str:
    from services.telematics.webhook_url import mint_token
    return mint_token(tid, provider_short)


def _mojio_sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ═════════════════════════════════════════════════════════════════
# 1. Provider registration
# ═════════════════════════════════════════════════════════════════
def test_register_telematics_kind_returns_both_providers():
    from services.telematics import (
        MOJIO_PROVIDER_KEY,
        GEOTAB_PROVIDER_KEY,
        list_registered_telematics_provider_keys,
        get_provider_field_schemas,
    )
    keys = set(list_registered_telematics_provider_keys())
    assert MOJIO_PROVIDER_KEY in keys
    assert GEOTAB_PROVIDER_KEY in keys
    schemas = get_provider_field_schemas()
    for k in (MOJIO_PROVIDER_KEY, GEOTAB_PROVIDER_KEY):
        assert "api_key" in schemas[k]
        assert schemas[k]["api_key"]["secret"] is True
        assert "account_id" in schemas[k]
        assert "webhook_secret" in schemas[k]


# ═════════════════════════════════════════════════════════════════
# 2. save_provider_config encrypts secrets at rest
# ═════════════════════════════════════════════════════════════════
def test_save_provider_config_encrypts_secrets():
    from services.telematics import MOJIO_PROVIDER_KEY

    tid = "p39-test-encrypt"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_provider_config(
            db, tid,
            provider_key=MOJIO_PROVIDER_KEY,
            api_key="ak_live_should_not_appear_plaintext",
            webhook_secret="whsec_xyz",
        )
        # Grep the raw row — no plaintext should be visible.
        row = await db.tenant_secrets.find_one({
            "tenant_id": tid, "provider_key": MOJIO_PROVIDER_KEY,
        })
        assert row is not None
        # Row should carry ciphertext + IV, never the plaintext string.
        assert "ak_live_should_not_appear_plaintext" not in json.dumps(row, default=str)
        assert "whsec_xyz" not in json.dumps(row, default=str)
        # ``services.secrets.crypto`` fields — the row carries the AES-
        # 256-GCM triple (encrypted_blob + iv + auth_tag).
        assert "encrypted_blob" in row
        assert "iv" in row
        assert "auth_tag" in row
        # last_4 comes from the primary_secret_field (api_key).
        last_4 = row.get("last_4")
        assert isinstance(last_4, str) and last_4
        assert last_4 == "text", (
            f"last_4 should be the last 4 of the api_key value, "
            f"got {last_4!r}"
        )
        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3. GET /webhook-url returns a signed URL that verifies
# ═════════════════════════════════════════════════════════════════
def test_webhook_url_endpoint_returns_signed_url():
    from services.telematics.webhook_url import (
        build_webhook_url, mint_token, verify_token,
    )
    tid = "p39-tenant-url"
    url = build_webhook_url(
        base_origin="https://api.example.test",
        tenant_id=tid,
        provider_short="mojio",
    )
    # URL contains both required query params.
    assert "?tid=" in url or "&tid=" in url
    assert "&t=" in url or "?t=" in url
    # Round-trip: extract the token from the URL and verify it.
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(url).query)
    assert qs["tid"] == [tid]
    token = qs["t"][0]
    assert verify_token(tenant_id=tid, provider_short="mojio", token=token) is True


# ═════════════════════════════════════════════════════════════════
# 4. Webhook rejects invalid tenant token → 401
# ═════════════════════════════════════════════════════════════════
def test_webhook_rejects_invalid_tenant_token_401():
    from fastapi import HTTPException
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics.webhook_url import mint_token

    tid = "p39-tenant-401"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid)
        # Legit token for a DIFFERENT tenant — cross-tenant reuse attempt.
        bad_token = mint_token("other-tenant", "mojio")
        req = _FakeRequest(body=b'{"x":1}', headers={})
        with pytest.raises(HTTPException) as exc:
            await telematics_webhook(
                provider_short="mojio",
                request=req,
                tid=tid,
                t=bad_token,
                secret=None,
            )
        assert exc.value.status_code == 401
        assert "invalid tenant token" in str(exc.value.detail)
        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5. Mojio webhook rejects invalid body signature → 401
# ═════════════════════════════════════════════════════════════════
def test_mojio_webhook_rejects_invalid_signature_401():
    from fastapi import HTTPException
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import MOJIO_PROVIDER_KEY

    tid = "p39-tenant-mojio-badsig"
    secret = "whsec_mojio_test"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=MOJIO_PROVIDER_KEY, webhook_secret=secret,
        )
        body = b'{"VehicleId":"v1","Latitude":33.5,"Longitude":-112.0,"Timestamp":"2026-02-16T10:00:00Z"}'
        # WRONG signature (over a different body).
        wrong_sig = _mojio_sign(b'{"different":"body"}', secret)
        req = _FakeRequest(body=body, headers={"x-mojio-signature": wrong_sig})
        token = _mint_url_token(tid, "mojio")
        with pytest.raises(HTTPException) as exc:
            await telematics_webhook(
                provider_short="mojio", request=req, tid=tid, t=token, secret=None,
            )
        assert exc.value.status_code == 401
        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 6. Mojio webhook accepts valid signature → 200, persists ping
# ═════════════════════════════════════════════════════════════════
def test_mojio_webhook_accepts_valid_signature_200_persists_ping():
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import MOJIO_PROVIDER_KEY

    tid = "p39-tenant-mojio-ok"
    secret = "whsec_mojio_ok"
    vid = "veh-mojio-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=MOJIO_PROVIDER_KEY, webhook_secret=secret,
        )
        body_dict = {
            "VehicleId": vid,
            "Latitude": 33.5,
            "Longitude": -112.0,
            "Timestamp": "2026-02-16T10:00:00Z",
            "Heading": 90.0,
            "SpeedKmh": 36.0,
            "EventId": "evt-1",
        }
        body = json.dumps(body_dict).encode()
        sig = _mojio_sign(body, secret)
        req = _FakeRequest(body=body, headers={"x-mojio-signature": sig})
        token = _mint_url_token(tid, "mojio")
        resp = await telematics_webhook(
            provider_short="mojio", request=req, tid=tid, t=token, secret=None,
        )
        assert resp.ok is True
        assert resp.status == "persisted"

        row = await db.gps_pings.find_one({"tenant_id": tid, "external_vehicle_id": vid})
        assert row is not None
        assert row["source"] == "telematics_mojio"
        assert row["telematics_provider"] == "mojio"
        assert row["lat"] == 33.5
        assert row["lon"] == -112.0
        # 36 km/h == 10 m/s
        assert abs((row["speed_mps"] or 0) - 10.0) < 0.01
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 7. Geotab webhook rejects missing shared secret → 401
# ═════════════════════════════════════════════════════════════════
def test_geotab_webhook_rejects_missing_shared_secret_401():
    from fastapi import HTTPException
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import GEOTAB_PROVIDER_KEY

    tid = "p39-tenant-geotab-nosec"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=GEOTAB_PROVIDER_KEY, webhook_secret="whsec_geotab",
        )
        body = b'{"deviceId":"g1","latitude":1.0,"longitude":2.0,"dateTime":"2026-02-16T10:00:00Z"}'
        # NO X-Telematics-Secret header, NO ?secret= query.
        req = _FakeRequest(body=body, headers={})
        token = _mint_url_token(tid, "geotab")
        with pytest.raises(HTTPException) as exc:
            await telematics_webhook(
                provider_short="geotab", request=req, tid=tid, t=token, secret=None,
            )
        assert exc.value.status_code == 401
        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 8. Geotab webhook accepts matching shared secret → 200
# ═════════════════════════════════════════════════════════════════
def test_geotab_webhook_accepts_matching_shared_secret_200():
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import GEOTAB_PROVIDER_KEY

    tid = "p39-tenant-geotab-ok"
    secret = "whsec_geotab_ok"
    vid = "veh-geotab-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=GEOTAB_PROVIDER_KEY, webhook_secret=secret,
        )
        body = json.dumps({
            "deviceId": vid,
            "latitude": 33.5,
            "longitude": -112.0,
            "dateTime": "2026-02-16T10:00:00Z",
            "speed": 72.0,  # kmh
            "bearing": 45.0,
            "notificationId": "notif-1",
        }).encode()
        req = _FakeRequest(body=body, headers={"x-telematics-secret": secret})
        token = _mint_url_token(tid, "geotab")
        resp = await telematics_webhook(
            provider_short="geotab", request=req, tid=tid, t=token, secret=None,
        )
        assert resp.status == "persisted"
        row = await db.gps_pings.find_one({"tenant_id": tid, "external_vehicle_id": vid})
        assert row is not None
        assert row["source"] == "telematics_geotab_webhook"
        # 72 km/h == 20 m/s
        assert abs((row["speed_mps"] or 0) - 20.0) < 0.01
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 9. Webhook idempotency — same (vehicle_id, ts) → duplicate
# ═════════════════════════════════════════════════════════════════
def test_webhook_idempotency_duplicate_event_id_returns_duplicate_shape():
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import MOJIO_PROVIDER_KEY

    tid = "p39-tenant-idem"
    secret = "whsec_idem"
    vid = "veh-idem-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=MOJIO_PROVIDER_KEY, webhook_secret=secret,
        )
        body = json.dumps({
            "VehicleId": vid,
            "Latitude": 33.5,
            "Longitude": -112.0,
            "Timestamp": "2026-02-16T10:00:00Z",
            "EventId": "same-evt",
        }).encode()
        sig = _mojio_sign(body, secret)
        req1 = _FakeRequest(body=body, headers={"x-mojio-signature": sig})
        req2 = _FakeRequest(body=body, headers={"x-mojio-signature": sig})
        token = _mint_url_token(tid, "mojio")
        r1 = await telematics_webhook(
            provider_short="mojio", request=req1, tid=tid, t=token, secret=None,
        )
        r2 = await telematics_webhook(
            provider_short="mojio", request=req2, tid=tid, t=token, secret=None,
        )
        assert r1.status == "persisted"
        assert r2.status == "duplicate"
        assert r2.ok is True
        # Only ONE row in the DB.
        count = await db.gps_pings.count_documents({
            "tenant_id": tid, "external_vehicle_id": vid,
        })
        assert count == 1
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 10. Unmapped vehicle → ping stored with user_id null
# ═════════════════════════════════════════════════════════════════
def test_webhook_unmapped_vehicle_stores_ping_with_null_technician():
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import MOJIO_PROVIDER_KEY

    tid = "p39-tenant-unmapped"
    secret = "whsec_unmapped"
    vid = "veh-unmapped-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=MOJIO_PROVIDER_KEY, webhook_secret=secret,
        )
        body = json.dumps({
            "VehicleId": vid,
            "Latitude": 33.5,
            "Longitude": -112.0,
            "Timestamp": "2026-02-16T10:00:00Z",
        }).encode()
        sig = _mojio_sign(body, secret)
        req = _FakeRequest(body=body, headers={"x-mojio-signature": sig})
        token = _mint_url_token(tid, "mojio")
        await telematics_webhook(
            provider_short="mojio", request=req, tid=tid, t=token, secret=None,
        )
        row = await db.gps_pings.find_one({"tenant_id": tid, "external_vehicle_id": vid})
        assert row is not None
        assert row["user_id"] is None, (
            f"unmapped vehicle should store null user_id; got {row.get('user_id')!r}"
        )
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 11. Mapped vehicle → ping stored with technician user_id
# ═════════════════════════════════════════════════════════════════
def test_webhook_mapped_vehicle_stores_ping_with_technician_id():
    from routers.telematics_webhooks import telematics_webhook
    from services.telematics import MOJIO_PROVIDER_KEY

    tid = "p39-tenant-mapped"
    secret = "whsec_mapped"
    vid = "veh-mapped-1"
    tech_uid = "tech-mapped-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        await _seed_tenant(db, tid)
        await _seed_technician(db, tid, tech_uid)
        await _seed_provider_config(
            db, tid, provider_key=MOJIO_PROVIDER_KEY, webhook_secret=secret,
        )
        await db.telematics_vehicle_links.insert_one({
            "id": "link-mapped-1",
            "tenant_id": tid,
            "external_vehicle_id": vid,
            "technician_user_id": tech_uid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        body = json.dumps({
            "VehicleId": vid, "Latitude": 33.5, "Longitude": -112.0,
            "Timestamp": "2026-02-16T10:00:00Z",
        }).encode()
        sig = _mojio_sign(body, secret)
        req = _FakeRequest(body=body, headers={"x-mojio-signature": sig})
        token = _mint_url_token(tid, "mojio")
        await telematics_webhook(
            provider_short="mojio", request=req, tid=tid, t=token, secret=None,
        )
        row = await db.gps_pings.find_one({"tenant_id": tid, "external_vehicle_id": vid})
        assert row["user_id"] == tech_uid
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 12. Vehicle-links CRUD is tenant-scoped
# ═════════════════════════════════════════════════════════════════
def test_vehicle_links_crud_tenant_scoped():
    from routers.telematics_webhooks import (
        list_vehicle_links, create_vehicle_link, delete_vehicle_link,
        CreateVehicleLinkBody,
    )
    from fastapi import HTTPException

    tid_a = "p39-crud-a"
    tid_b = "p39-crud-b"
    tech_a = "tech-a-1"
    tech_b = "tech-b-1"

    async def _go(db):
        await _wipe(db, [tid_a, tid_b])
        await _seed_tenant(db, tid_a)
        await _seed_tenant(db, tid_b)
        await _seed_technician(db, tid_a, tech_a)
        await _seed_technician(db, tid_b, tech_b)

        admin_user = {"role": "admin"}
        # Create for A.
        r_a = await create_vehicle_link(
            body=CreateVehicleLinkBody(
                external_vehicle_id="veh-a-1",
                technician_user_id=tech_a,
                backfill=False,
            ),
            user=admin_user,
            tenant={"id": tid_a},
        )
        # Create for B.
        r_b = await create_vehicle_link(
            body=CreateVehicleLinkBody(
                external_vehicle_id="veh-b-1",
                technician_user_id=tech_b,
                backfill=False,
            ),
            user=admin_user,
            tenant={"id": tid_b},
        )
        # Tenant A cannot see B's link.
        listing_a = await list_vehicle_links(user=admin_user, tenant={"id": tid_a})
        vids_a = {row.external_vehicle_id for row in listing_a.links}
        assert vids_a == {"veh-a-1"}

        # Tenant A cannot delete B's link.
        with pytest.raises(HTTPException) as exc:
            await delete_vehicle_link(
                link_id=r_b.link.id, user=admin_user, tenant={"id": tid_a},
            )
        assert exc.value.status_code == 404
        # B's link still there.
        b_row = await db.telematics_vehicle_links.find_one({"id": r_b.link.id})
        assert b_row is not None

        # A CAN delete A's link.
        del_res = await delete_vehicle_link(
            link_id=r_a.link.id, user=admin_user, tenant={"id": tid_a},
        )
        assert del_res["removed"] is True
        await _wipe(db, [tid_a, tid_b])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 13. Unmapped-vehicles endpoint returns last-30-days null-tech only
# ═════════════════════════════════════════════════════════════════
def test_unmapped_vehicles_endpoint_returns_last_30_days_null_tech_only():
    from routers.telematics_webhooks import list_unmapped_vehicles

    tid = "p39-unmapped-list"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=["v-recent", "v-old", "v-mapped"])
        await _seed_tenant(db, tid)
        now = datetime.now(timezone.utc)
        recent = now.isoformat()
        old = (now - timedelta(days=45)).isoformat()
        # v-recent: unmapped, within window → SHOULD appear
        await db.gps_pings.insert_one({
            "id": "pg1", "tenant_id": tid, "user_id": None,
            "source": "telematics_mojio", "captured_at": recent,
            "received_at": recent, "external_vehicle_id": "v-recent",
            "lat": 33.5, "lon": -112.0,
        })
        # v-old: unmapped, OUTSIDE window → should NOT appear
        await db.gps_pings.insert_one({
            "id": "pg2", "tenant_id": tid, "user_id": None,
            "source": "telematics_mojio", "captured_at": old,
            "received_at": old, "external_vehicle_id": "v-old",
            "lat": 33.5, "lon": -112.0,
        })
        # v-mapped: has a user_id → should NOT appear
        await db.gps_pings.insert_one({
            "id": "pg3", "tenant_id": tid, "user_id": "u-1",
            "source": "telematics_mojio", "captured_at": recent,
            "received_at": recent, "external_vehicle_id": "v-mapped",
            "lat": 33.5, "lon": -112.0,
        })
        admin_user = {"role": "admin"}
        res = await list_unmapped_vehicles(user=admin_user, tenant={"id": tid})
        vids = {row.external_vehicle_id for row in res.vehicles}
        assert vids == {"v-recent"}
        # And it carries decorated stats.
        assert res.vehicles[0].last_seen_at == recent
        assert res.vehicles[0].unmapped_pings_count == 1
        await _wipe(db, [tid], vehicle_ids=["v-recent", "v-old", "v-mapped"])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 14. Vehicle-links list decorates rows with last_seen_at + count
# ═════════════════════════════════════════════════════════════════
def test_vehicle_links_stats_returns_last_seen_and_count():
    from routers.telematics_webhooks import (
        list_vehicle_links, create_vehicle_link, CreateVehicleLinkBody,
    )

    tid = "p39-stats"
    tech = "tech-stats-1"
    vid = "veh-stats-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _seed_tenant(db, tid)
        await _seed_technician(db, tid, tech)
        admin_user = {"role": "admin"}
        await create_vehicle_link(
            body=CreateVehicleLinkBody(
                external_vehicle_id=vid,
                technician_user_id=tech,
                backfill=False,
            ),
            user=admin_user,
            tenant={"id": tid},
        )
        # Seed a mix of pings — 2 unmapped (user_id=None) + 1 mapped.
        base = datetime.now(timezone.utc)
        for i, off in enumerate([-2, -1, 0]):
            ts = (base + timedelta(minutes=off)).isoformat()
            await db.gps_pings.insert_one({
                "id": f"pg-{i}", "tenant_id": tid,
                "user_id": tech if i == 2 else None,
                "source": "telematics_mojio",
                "captured_at": ts, "received_at": ts,
                "external_vehicle_id": vid,
                "lat": 33.5, "lon": -112.0,
            })
        expected_last = (base + timedelta(minutes=0)).isoformat()
        listing = await list_vehicle_links(user=admin_user, tenant={"id": tid})
        assert len(listing.links) == 1
        row = listing.links[0]
        assert row.last_seen_at == expected_last
        # Two of three pings are unmapped.
        assert row.unmapped_pings_count == 2
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 15. Create link with backfill=True re-attributes null-tech pings
# ═════════════════════════════════════════════════════════════════
def test_create_link_with_backfill_updates_null_tech_pings():
    from routers.telematics_webhooks import (
        create_vehicle_link, CreateVehicleLinkBody,
    )

    tid = "p39-backfill-on"
    tech = "tech-bfon"
    vid = "veh-bfon"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _seed_tenant(db, tid)
        await _seed_technician(db, tid, tech)
        # Seed 5 null-tech pings + 1 already-mapped-to-someone-else.
        base = datetime.now(timezone.utc)
        for i in range(5):
            ts = (base + timedelta(minutes=i)).isoformat()
            await db.gps_pings.insert_one({
                "id": f"pg-null-{i}", "tenant_id": tid, "user_id": None,
                "source": "telematics_mojio",
                "captured_at": ts, "received_at": ts,
                "external_vehicle_id": vid,
                "lat": 33.5, "lon": -112.0,
            })
        # Different-tech ping — must NOT be touched.
        await db.gps_pings.insert_one({
            "id": "pg-other-tech", "tenant_id": tid, "user_id": "some-other-tech",
            "source": "telematics_mojio",
            "captured_at": (base + timedelta(minutes=100)).isoformat(),
            "received_at": (base + timedelta(minutes=100)).isoformat(),
            "external_vehicle_id": vid,
            "lat": 33.5, "lon": -112.0,
        })
        admin_user = {"role": "admin"}
        res = await create_vehicle_link(
            body=CreateVehicleLinkBody(
                external_vehicle_id=vid,
                technician_user_id=tech,
                backfill=True,
            ),
            user=admin_user,
            tenant={"id": tid},
        )
        assert res.backfilled == 5
        # All 5 null pings now attributed to the mapped tech.
        n = await db.gps_pings.count_documents({
            "tenant_id": tid, "external_vehicle_id": vid, "user_id": tech,
        })
        assert n == 5
        # The other-tech ping is untouched.
        other = await db.gps_pings.find_one({"id": "pg-other-tech"})
        assert other["user_id"] == "some-other-tech"
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 16. Create link with backfill=False leaves pings null
# ═════════════════════════════════════════════════════════════════
def test_create_link_without_backfill_leaves_pings_null():
    from routers.telematics_webhooks import (
        create_vehicle_link, CreateVehicleLinkBody,
    )

    tid = "p39-backfill-off"
    tech = "tech-bfoff"
    vid = "veh-bfoff"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _seed_tenant(db, tid)
        await _seed_technician(db, tid, tech)
        base = datetime.now(timezone.utc)
        for i in range(3):
            ts = (base + timedelta(minutes=i)).isoformat()
            await db.gps_pings.insert_one({
                "id": f"pg-{i}", "tenant_id": tid, "user_id": None,
                "source": "telematics_mojio",
                "captured_at": ts, "received_at": ts,
                "external_vehicle_id": vid,
                "lat": 33.5, "lon": -112.0,
            })
        admin_user = {"role": "admin"}
        res = await create_vehicle_link(
            body=CreateVehicleLinkBody(
                external_vehicle_id=vid,
                technician_user_id=tech,
                backfill=False,
            ),
            user=admin_user,
            tenant={"id": tid},
        )
        assert res.backfilled == 0
        # All 3 pings still null-tech.
        n = await db.gps_pings.count_documents({
            "tenant_id": tid, "external_vehicle_id": vid, "user_id": None,
        })
        assert n == 3
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 17. Geotab poller disabled by default
# ═════════════════════════════════════════════════════════════════
def test_geotab_poller_disabled_by_default(monkeypatch):
    from services import telematics_geotab_poller as poller
    monkeypatch.delenv("TELEMATICS_GEOTAB_POLL_ENABLED", raising=False)
    assert poller.poll_enabled() is False
    started = poller.start_scheduler()
    assert started is False


# ═════════════════════════════════════════════════════════════════
# 18. Poller reads DeviceStatusInfo + persists a ping
# ═════════════════════════════════════════════════════════════════
def test_geotab_poller_reads_devicestatusinfo_and_persists():
    from services import telematics_geotab_poller as poller
    from services.telematics import GEOTAB_PROVIDER_KEY

    tid = "p39-poll-persist"
    vid = "veh-poll-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        poller.reset_cooldown_for_tests()
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=GEOTAB_PROVIDER_KEY,
            webhook_secret="whsec", api_key="sess-1", account_id="db-x",
        )
        fixture = [{
            "device": {"id": vid},
            "latitude": 33.5,
            "longitude": -112.0,
            "dateTime": "2026-02-16T10:00:00Z",
            "speed": 36.0,
            "bearing": 90.0,
        }]

        async def _fake_call(*args, **kwargs):
            return fixture

        with patch.object(poller, "_call_geotab_api", side_effect=_fake_call):
            res = await poller.poll_tenant_once(tid)

        assert res["status"] == "ok"
        assert res["persisted"] == 1
        row = await db.gps_pings.find_one({"tenant_id": tid, "external_vehicle_id": vid})
        assert row is not None
        assert row["source"] == "telematics_geotab_poll"
        assert abs((row["speed_mps"] or 0) - 10.0) < 0.01
        assert row["heading"] == 90.0
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 19. Poller dedups on repeated dateTime
# ═════════════════════════════════════════════════════════════════
def test_geotab_poller_dedup_on_repeated_dateTime():
    from services import telematics_geotab_poller as poller
    from services.telematics import GEOTAB_PROVIDER_KEY

    tid = "p39-poll-dedup"
    vid = "veh-poll-dedup-1"

    async def _go(db):
        await _wipe(db, [tid], vehicle_ids=[vid])
        await _ensure_dedup_index(db)
        poller.reset_cooldown_for_tests()
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=GEOTAB_PROVIDER_KEY,
            webhook_secret="whsec", api_key="sess-2", account_id="db-y",
        )
        fixture = [{
            "device": {"id": vid},
            "latitude": 33.5, "longitude": -112.0,
            "dateTime": "2026-02-16T11:00:00Z",
            "speed": 0.0, "bearing": 0.0,
        }]

        async def _fake_call(*args, **kwargs):
            return fixture

        with patch.object(poller, "_call_geotab_api", side_effect=_fake_call):
            r1 = await poller.poll_tenant_once(tid)
            r2 = await poller.poll_tenant_once(tid)

        assert r1["persisted"] == 1
        assert r2["persisted"] == 0
        assert r2["duplicates"] == 1
        n = await db.gps_pings.count_documents({
            "tenant_id": tid, "external_vehicle_id": vid,
        })
        assert n == 1
        await _wipe(db, [tid], vehicle_ids=[vid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 20. Poller backs off after auth error
# ═════════════════════════════════════════════════════════════════
def test_geotab_poller_backoff_on_auth_error():
    from services import telematics_geotab_poller as poller
    from services.telematics import GEOTAB_PROVIDER_KEY

    tid = "p39-poll-auth-err"

    async def _go(db):
        await _wipe(db, [tid])
        poller.reset_cooldown_for_tests(tid)
        await _seed_tenant(db, tid)
        await _seed_provider_config(
            db, tid, provider_key=GEOTAB_PROVIDER_KEY,
            webhook_secret="whsec", api_key="bad-sess", account_id="db-z",
        )

        async def _fake_call(*args, **kwargs):
            raise ValueError("MyGeotab RPC error: {'name':'InvalidUserException'}")

        with patch.object(poller, "_call_geotab_api", side_effect=_fake_call):
            res = await poller.poll_tenant_once(tid)

        assert res["status"] == "auth_error"
        # last_error stamped on the tenant's connection row.
        row = await db.tenant_secrets.find_one(
            {"tenant_id": tid, "provider_key": GEOTAB_PROVIDER_KEY},
        )
        assert row.get("last_error"), "auth_error must stamp last_error"

        # Next tick is under cooldown → does NOT hit the API.
        # We can prove this by giving the fake call a fresh side-effect
        # that would raise a *different* error; the tick should return
        # ``cooldown`` without invoking it.
        called_after_cooldown = {"n": 0}

        async def _fake_call_never_called(*args, **kwargs):
            called_after_cooldown["n"] += 1
            return []

        with patch.object(poller, "_call_geotab_api", side_effect=_fake_call_never_called):
            for _ in range(5):
                res2 = await poller.poll_tenant_once(tid)
                assert res2["status"] == "cooldown"
        assert called_after_cooldown["n"] == 0

        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# Test-only FastAPI Request fake — we can't build a real Starlette
# Request in a unit test cheaply, but the receiver only uses
# ``.body()``, ``.headers``, ``.url.scheme``, ``.url.netloc``, and
# proxy-header lookups.  A minimal duck-typed stand-in is fine.
# ═════════════════════════════════════════════════════════════════
class _FakeURL:
    def __init__(self, scheme: str = "https", netloc: str = "api.test") -> None:
        self.scheme = scheme
        self.netloc = netloc


class _FakeRequest:
    def __init__(self, *, body: bytes, headers: Dict[str, str]) -> None:
        self._body = body
        self.headers = headers
        self.url = _FakeURL()

    async def body(self) -> bytes:
        return self._body
