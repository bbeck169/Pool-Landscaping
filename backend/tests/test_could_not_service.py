"""Feb-2026 · Phase 1 — Could-Not-Service tests (endpoint + reasons CRUD)."""
from __future__ import annotations

import asyncio, uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from utils import hash_password


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _run(coro):
    loop = asyncio.new_event_loop()
    try: return loop.run_until_complete(coro)
    finally: loop.close()


TID  = f"TEST_cns_{uuid.uuid4().hex[:6]}"
CID  = f"cust_cns_{uuid.uuid4().hex[:6]}"
TUID = f"tech_cns_{uuid.uuid4().hex[:6]}"
PUID = f"portal_cns_{uuid.uuid4().hex[:6]}"
AUID = f"admin_cns_{uuid.uuid4().hex[:6]}"
JID  = f"job_cns_{uuid.uuid4().hex[:6]}"
FID  = f"file_cns_{uuid.uuid4().hex[:6]}"
T_EMAIL = f"tech_{uuid.uuid4().hex[:6]}@cnstest.example.com"
P_EMAIL = f"portal_{uuid.uuid4().hex[:6]}@cnstest.example.com"
A_EMAIL = f"admin_{uuid.uuid4().hex[:6]}@cnstest.example.com"


def _seed(*, blocked=False, sms_opt_in=True, phone="+15550001234",
            status="scheduled"):
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TID})
            await db.customers.delete_many({"id": CID})
            await db.users.delete_many({"id": {"$in": [TUID, PUID, AUID]}})
            await db.jobs.delete_many({"id": JID})
            await db.files.delete_many({"id": FID})
            await db.communications.delete_many({"job_id": JID})
            await db.job_outcome_reasons.delete_many({"tenant_id": TID})
            await db.tenants.insert_one({"id": TID, "name": "CNS Co",
                                           "company_name": "CNS Co", "active": True})
            await db.users.insert_many([
                {"id": TUID, "tenant_id": TID, "name": "Mike Rivera",
                 "first_name": "Mike", "email": T_EMAIL,
                 "password_hash": hash_password("password123"),
                 "role": "technician", "active": True},
                {"id": AUID, "tenant_id": TID, "name": "Admin Adele",
                 "email": A_EMAIL, "password_hash": hash_password("password123"),
                 "role": "admin", "active": True},
                {"id": PUID, "tenant_id": TID, "name": "Portal", "email": P_EMAIL,
                 "password_hash": hash_password("password123"),
                 "role": "customer", "customer_id": CID, "active": True},
            ])
            cust = {"id": CID, "tenant_id": TID, "name": "Jane Doe",
                     "first_name": "Jane", "phone": phone,
                     "is_demo_account": True}
            if not sms_opt_in: cust["sms_opt_in"] = False
            if blocked: cust["blocked"] = True
            await db.customers.insert_one(cust)
            await db.jobs.insert_one({"id": JID, "tenant_id": TID,
                                        "customer_id": CID, "technician_id": TUID,
                                        "status": status})
            await db.files.insert_one({"id": FID, "tenant_id": TID,
                                         "filename": "photo.jpg"})
        finally: c.close()
    _run(_go())


def _cleanup():
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TID})
            await db.customers.delete_many({"id": CID})
            await db.users.delete_many({"id": {"$in": [TUID, PUID, AUID]}})
            await db.jobs.delete_many({"id": JID})
            await db.files.delete_many({"id": FID})
            await db.communications.delete_many({"job_id": JID})
            await db.job_outcome_reasons.delete_many({"tenant_id": TID})
        finally: c.close()
    _run(_go())


def _login(email):
    return requests.post(f"{API}/auth/login",
                          json={"email": email, "password": "password123"},
                          timeout=10).json()["access_token"]


def _reasons(tok):
    return requests.get(f"{API}/settings/job-outcome-reasons",
                         headers={"Authorization": f"Bearer {tok}"},
                         timeout=10).json()["reasons"]


def _post_cns(tok, body):
    return requests.post(f"{API}/jobs/{JID}/could-not-service",
                          headers={"Authorization": f"Bearer {tok}",
                                    "Content-Type": "application/json"},
                          json=body, timeout=10)


# ─── reasons CRUD ───────────────────────────────────────────────────
def test_reasons_auto_hydrate_defaults_on_first_get():
    _seed()
    try:
        tok = _login(T_EMAIL)
        rows = _reasons(tok)
        keys = [r["key"] for r in rows]
        for k in ("locked_out","no_water","unsafe_conditions","weather",
                   "customer_refused","equipment_failure","other"):
            assert k in keys
        assert all(r["is_default"] for r in rows)
    finally: _cleanup()


def test_admin_can_create_and_patch_technician_cannot():
    _seed()
    try:
        adm = _login(A_EMAIL); tec = _login(T_EMAIL)
        # tech blocked on create
        r = requests.post(f"{API}/settings/job-outcome-reasons",
                           headers={"Authorization": f"Bearer {tec}"},
                           json={"label": "New reason"}, timeout=10)
        assert r.status_code == 403
        # admin can
        r = requests.post(f"{API}/settings/job-outcome-reasons",
                           headers={"Authorization": f"Bearer {adm}"},
                           json={"label": "Chemical spill"}, timeout=10)
        assert r.status_code == 200
        rid = r.json()["id"]; assert r.json()["key"] == "chemical_spill"
        # patch label
        r = requests.patch(f"{API}/settings/job-outcome-reasons/{rid}",
                            headers={"Authorization": f"Bearer {adm}"},
                            json={"label": "Hazmat"}, timeout=10)
        assert r.status_code == 200; assert r.json()["label"] == "Hazmat"
    finally: _cleanup()


def test_default_reason_cannot_be_hard_deleted():
    _seed()
    try:
        adm = _login(A_EMAIL); _reasons(_login(T_EMAIL))  # hydrate
        rows = _reasons(adm)
        default = next(r for r in rows if r["is_default"])
        r = requests.delete(f"{API}/settings/job-outcome-reasons/{default['id']}",
                             headers={"Authorization": f"Bearer {adm}"}, timeout=10)
        assert r.status_code == 400
        # But soft-delete is allowed
        r = requests.patch(f"{API}/settings/job-outcome-reasons/{default['id']}",
                            headers={"Authorization": f"Bearer {adm}"},
                            json={"active": False}, timeout=10)
        assert r.status_code == 200 and r.json()["active"] is False
    finally: _cleanup()


# ─── endpoint ───────────────────────────────────────────────────────
def _pick_reason(tok, key="locked_out"):
    return next(r for r in _reasons(tok) if r["key"] == key)["id"]


def test_happy_path_flips_status_and_sends_sms():
    _seed()
    try:
        tok = _login(T_EMAIL); rid = _pick_reason(tok)
        r = _post_cns(tok, {"reason_id": rid, "reason_notes": "",
                              "photo_file_ids": [FID]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "could_not_service"
        assert body["job"]["status"] == "could_not_service"
        assert body["job"]["outcome_reason_id"] == rid
        assert body["job"]["outcome_photo_file_ids"] == [FID]
        assert body["sms_result"]["sent"] is True
        # Communications row inserted
        async def _find():
            c = AsyncIOMotorClient(_ENV["MONGO_URL"])
            db = c[_ENV["DB_NAME"]]
            try:
                return await db.communications.find_one(
                    {"job_id": JID, "template_key": "job_could_not_service"},
                    {"_id": 0})
            finally: c.close()
        comm = _run(_find())
        assert comm and "Locked out" in comm["body"] and "Mike" in comm["body"]
        assert "Reply STOP" in comm["body"]
    finally: _cleanup()


def test_other_reason_uses_notes_or_default_phrase():
    _seed()
    try:
        tok = _login(T_EMAIL); rid = _pick_reason(tok, "other")
        # With notes → body uses notes
        r = _post_cns(tok, {"reason_id": rid,
                              "reason_notes": "pool cover jammed",
                              "photo_file_ids": [FID]})
        assert r.status_code == 200
        async def _last():
            c = AsyncIOMotorClient(_ENV["MONGO_URL"])
            db = c[_ENV["DB_NAME"]]
            try:
                return await db.communications.find_one(
                    {"job_id": JID}, {"_id": 0}, sort=[("sent_at", -1)])
            finally: c.close()
        comm = _run(_last())
        assert comm and "pool cover jammed" in comm["body"]
    finally: _cleanup()


def test_zero_photos_rejected_with_422():
    _seed()
    try:
        tok = _login(T_EMAIL); rid = _pick_reason(tok)
        r = _post_cns(tok, {"reason_id": rid, "photo_file_ids": []})
        assert r.status_code == 422
    finally: _cleanup()


def test_already_completed_job_rejects_409():
    _seed(status="completed")
    try:
        tok = _login(T_EMAIL); rid = _pick_reason(tok)
        r = _post_cns(tok, {"reason_id": rid, "photo_file_ids": [FID]})
        assert r.status_code == 409
    finally: _cleanup()


def test_guard_hit_still_flips_status_no_sms():
    _seed(sms_opt_in=False)
    try:
        tok = _login(T_EMAIL); rid = _pick_reason(tok)
        r = _post_cns(tok, {"reason_id": rid, "photo_file_ids": [FID]})
        assert r.status_code == 200
        body = r.json()
        assert body["job"]["status"] == "could_not_service"
        assert body["sms_result"]["sent"] is False
        assert body["sms_result"]["reason"] == "sms_opt_in_false"
    finally: _cleanup()


def test_portal_customer_forbidden():
    _seed()
    try:
        tok = _login(P_EMAIL)
        # Portal customer can't even list reasons
        r = requests.get(f"{API}/settings/job-outcome-reasons",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        assert r.status_code == 403
    finally: _cleanup()
