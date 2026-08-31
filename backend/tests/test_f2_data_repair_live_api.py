"""Phase F2 live-API integration tests for /api/admin/data-repair/*.

Run order matters (pytest executes top-to-bottom within a module):
  1. auth/RBAC negatives
  2. dry-run baseline + no-write proof
  3. apply happy path (MUTATES DB — soft-deletes orphan-customer jobs)
  4. apply idempotency
  5. history verification
  6. post-apply dry-run proof
"""
import os

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or _env.get("REACT_APP_BACKEND_URL")).rstrip("/")

DRY_RUN = f"{BASE_URL}/api/admin/data-repair/jobs/dry-run"
APPLY = f"{BASE_URL}/api/admin/data-repair/jobs/apply"
HISTORY = f"{BASE_URL}/api/admin/data-repair/history"

ALLOWED_FIXTURE_NAMES = {"Confirm Case", "Water Bodies Test", "Lynn Merril"}

# module-level state shared across ordered tests
STATE = {}


def _login(email, password="password123"):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:300]}"
    tok = r.json().get("access_token")
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def super_headers():
    return _login("super@aquaterra.com")


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


# ── 1. RBAC negatives ────────────────────────────────────────────────
class TestRbac:
    def test_dry_run_anonymous_rejected(self):
        r = requests.get(DRY_RUN, timeout=60)
        assert r.status_code in (401, 403), r.text[:300]

    def test_dry_run_admin_forbidden(self, admin_headers):
        me = requests.get(f"{BASE_URL}/api/auth/me",
                          headers=admin_headers, timeout=60)
        assert me.status_code == 200
        assert me.json().get("role") == "admin", me.json().get("role")
        r = requests.get(DRY_RUN, headers=admin_headers, timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:300]}"

    def test_apply_admin_forbidden(self, admin_headers):
        r = requests.post(APPLY, headers=admin_headers, json={
            "confirm_token": "x" * 12,
            "dry_run_scan_timestamp": "2026-02-01T00:00:00Z",
        }, timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:300]}"

    def test_history_anonymous_rejected(self):
        r = requests.get(HISTORY, timeout=60)
        assert r.status_code in (401, 403), r.text[:300]

    def test_history_admin_forbidden(self, admin_headers):
        r = requests.get(HISTORY, headers=admin_headers, timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:300]}"


# ── 2. dry-run shape + read-only proof ───────────────────────────────
class TestDryRun:
    def test_dry_run_shape_and_baseline(self, super_headers):
        r = requests.get(DRY_RUN, headers=super_headers, timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:500]}"
        d = r.json()
        for key in ("confirm_token", "scan_timestamp",
                    "orphaned_customer_refs", "orphaned_technician_refs",
                    "unassigned_pending_jobs", "summary"):
            assert key in d, f"missing key {key}: {list(d)}"
        assert isinstance(d["orphaned_customer_refs"], list)
        s = d["summary"]
        assert "total_would_change" in s and "total_flagged_no_action" in s
        assert s["total_would_change"] == (
            len(d["orphaned_customer_refs"]) + len(d["orphaned_technician_refs"]))
        assert s["total_flagged_no_action"] == len(d["unassigned_pending_jobs"])
        STATE["baseline"] = d
        print("BASELINE summary:", s)
        print("orphan_cust names:",
              sorted({x.get("customer_name_denorm")
                      for x in d["orphaned_customer_refs"]}))
        print("unassigned titles:",
              [x.get("title") for x in d["unassigned_pending_jobs"]])

    def test_orphan_customer_rows_are_test_fixtures(self):
        d = STATE.get("baseline")
        assert d, "baseline dry-run did not run"
        names = {x.get("customer_name_denorm")
                 for x in d["orphaned_customer_refs"]}
        unexpected = names - ALLOWED_FIXTURE_NAMES
        assert not unexpected, (
            f"SAFETY ABORT: non-fixture customer names in orphan set: {unexpected}")
        for row in d["orphaned_customer_refs"]:
            assert row["would_action"] == "soft_delete"
        for row in d["orphaned_technician_refs"]:
            assert row["would_action"] == "null_technician_id"
        for row in d["unassigned_pending_jobs"]:
            assert row["would_action"] == "flag_only"

    def test_dry_run_performs_no_writes(self, super_headers):
        """Sample unaffected active jobs, snapshot updated_at, re-run
        dry-run, confirm nothing changed."""
        jr = requests.get(f"{BASE_URL}/api/jobs?limit=25",
                          headers=super_headers, timeout=120)
        assert jr.status_code == 200, jr.text[:300]
        payload = jr.json()
        jobs = payload if isinstance(payload, list) else payload.get("jobs", [])
        assert jobs, "no jobs returned for no-write sampling"
        before = {j.get("id"): (j.get("updated_at"), j.get("status"),
                               j.get("deleted_at")) for j in jobs[:25]}

        r = requests.get(DRY_RUN, headers=super_headers, timeout=180)
        assert r.status_code == 200

        jr2 = requests.get(f"{BASE_URL}/api/jobs?limit=25",
                           headers=super_headers, timeout=120)
        payload2 = jr2.json()
        jobs2 = payload2 if isinstance(payload2, list) else payload2.get("jobs", [])
        after = {j.get("id"): (j.get("updated_at"), j.get("status"),
                              j.get("deleted_at")) for j in jobs2[:25]}
        for jid, snap in before.items():
            if jid in after:
                assert after[jid] == snap, f"dry-run mutated job {jid}: {snap} -> {after[jid]}"


# ── 3. apply negatives ───────────────────────────────────────────────
class TestApplyValidation:
    def test_apply_bogus_token(self, super_headers):
        r = requests.post(APPLY, headers=super_headers, json={
            "confirm_token": "bogus-token-000000",
            "dry_run_scan_timestamp": "2026-02-01T00:00:00Z",
        }, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
        assert "confirm_token" in r.text, r.text[:300]

    def test_apply_wrong_scan_timestamp(self, super_headers):
        fresh = requests.get(DRY_RUN, headers=super_headers, timeout=180).json()
        r = requests.post(APPLY, headers=super_headers, json={
            "confirm_token": fresh["confirm_token"],
            "dry_run_scan_timestamp": "1999-01-01T00:00:00+00:00",
        }, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
        assert "scan_timestamp" in r.text, r.text[:300]


# ── 4. apply happy path (MUTATES DB) ─────────────────────────────────
class TestApplyHappyPath:
    def test_apply_matches_dry_run(self, super_headers):
        r = requests.get(DRY_RUN, headers=super_headers, timeout=180)
        assert r.status_code == 200
        d = r.json()
        names = {x.get("customer_name_denorm")
                 for x in d["orphaned_customer_refs"]}
        assert not (names - ALLOWED_FIXTURE_NAMES), (
            f"SAFETY ABORT before apply: {names - ALLOWED_FIXTURE_NAMES}")
        expected = d["summary"]["total_would_change"]
        STATE["expected_changes"] = expected
        STATE["target_ids"] = [x["job_id"] for x in d["orphaned_customer_refs"]]

        ar = requests.post(APPLY, headers=super_headers, json={
            "confirm_token": d["confirm_token"],
            "dry_run_scan_timestamp": d["scan_timestamp"],
        }, timeout=300)
        assert ar.status_code == 200, f"{ar.status_code} {ar.text[:500]}"
        a = ar.json()
        print("APPLY result:", {k: v for k, v in a.items() if k != "audit_log_ids"})
        assert a["run_id"] == d["confirm_token"]
        assert a["changes_applied"] == expected, (
            f"changes_applied={a['changes_applied']} expected={expected}")
        assert len(a["audit_log_ids"]) == a["changes_applied"]
        assert a["no_op"] is (expected == 0)
        STATE["run_id"] = a["run_id"]
        STATE["apply_payload"] = {
            "confirm_token": d["confirm_token"],
            "dry_run_scan_timestamp": d["scan_timestamp"],
        }

    def test_apply_idempotent_rerun(self, super_headers):
        payload = STATE.get("apply_payload")
        assert payload, "apply did not run"
        r = requests.post(APPLY, headers=super_headers, json=payload, timeout=300)
        assert r.status_code == 200, f"{r.status_code} {r.text[:500]}"
        a = r.json()
        assert a["changes_applied"] == 0, a
        assert a["no_op"] is True, a
        assert a["audit_log_ids"] == []


# ── 5. history ───────────────────────────────────────────────────────
class TestHistory:
    def test_history_contains_run(self, super_headers):
        run_id = STATE.get("run_id")
        assert run_id, "apply did not run"
        if STATE.get("expected_changes") == 0:
            pytest.skip("DB already repaired — apply was a legit no-op, "
                        "no new history run expected")
        r = requests.get(HISTORY, headers=super_headers, timeout=120)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert "runs" in d and "row_count" in d
        match = [x for x in d["runs"] if x["run_id"] == run_id]
        assert match, f"run_id {run_id} not in history runs {[x['run_id'] for x in d['runs']]}"
        run = match[0]
        assert len(run["changes"]) == STATE["expected_changes"], (
            f"history changes={len(run['changes'])} expected={STATE['expected_changes']}")
        for c in run["changes"]:
            assert c["class"] in {"orphaned_customer_ref", "orphaned_technician_ref"}
            assert c["action"] in {"soft_delete", "null_technician_id"}


# ── 6. post-apply proof ──────────────────────────────────────────────
class TestPostApplyProof:
    def test_orphan_customers_now_empty(self, super_headers):
        r = requests.get(DRY_RUN, headers=super_headers, timeout=180)
        assert r.status_code == 200
        d = r.json()
        print("POST-APPLY summary:", d["summary"])
        assert d["orphaned_customer_refs"] == [], d["orphaned_customer_refs"]
        assert d["orphaned_technician_refs"] == []
        assert d["summary"]["total_would_change"] == 0
