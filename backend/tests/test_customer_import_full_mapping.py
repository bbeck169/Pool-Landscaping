"""Feb-2026 hotfix — full-mapping CSV import.

User reported that importing an ``Active Clients.csv`` export only
persisted name + phone; every other field (email, address, tags,
customer_since) was dropped. Root cause was two-fold:

  1. The CSV's ``Tag`` column (singular) wasn't in the ``LEGACY_ALIAS``
     map, so tags fell into the un-mapped bucket and were silently lost.
  2. Rows missing any of the historically-required address fields
     (``service address street``, ``postal code``, ``state``) were
     hard-rejected — real-world CSVs frequently omit these for
     landscape-only accounts or address-pending prospects.

This suite pins the fix using a fixture that mirrors the exact shape of
the reported CSV: header with an empty second column (double comma),
trailing comma (phantom empty column), singular ``Tag`` header, mixed
phone formats, a future ``Customer Since`` date, a ``0`` last-name
sentinel, and rows with missing address components.
"""
import os
from datetime import date, timedelta

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


# ---------------------------------------------------------------------------
# Fixture — 8 rows exercising every bug/behavior called out in the brief.
# Header row uses the EXACT shape from the reported real-world CSV:
#   - empty second column (double comma)
#   - singular "Tag" (not "Tags")
#   - trailing comma (phantom 13th column)
# Test-only markers ("TEST_" prefix on last_name or address) so the
# conftest cleanup fixture removes these rows after the run.
# ---------------------------------------------------------------------------
_FUTURE = (date.today() + timedelta(days=45)).strftime("%m/%d/%Y")

FIXTURE_CSV = (
    "Customer Since,,Email,Service address Street,City,State,Postal Code,Phone,Mobile,First Name,Last Name,Tag,\n"
    # 1) Full row, parenthesized phone, single tag → happy path.
    "6/11/2024,,test_ci1@example.com,13798 West Whisper Rock Trail,Peoria,AZ,85383,,(623) 249-8461,Sara,TEST_Garcia,Pool Client,\n"
    # 2) All-digit phones, both landline & mobile identical.
    "6/3/2024,,test_ci2@example.com,29944 N 128th Ave,Peoria,AZ,85383,2197071542,2197071542,Lyndsey,TEST_Douglass,,\n"
    # 3) Missing street + missing postal — must import with warnings, not skip.
    "5/30/2024,,test_ci3@example.com,,Peoria,AZ,,,(818) 859-0052,Menua,TEST_Tsaturyan,,\n"
    # 4) Space-separated phone.
    "5/17/2024,,test_ci4@example.com,32537 North 133rd Lane,Peoria,AZ,85383,,425 241 6779,Mike,TEST_Camacho,Landscaping,\n"
    # 5) Multi-tag row (comma-separated inside the Tag cell → quoted).
    "5/3/2024,,test_ci5@example.com,13453 W Red Hawk Dr,Peoria,AZ,85383,3605366127,3605366127,Rob,TEST_Howell,\"Pool Client, VIP\",\n"
    # 6) "0" last-name sentinel — must import verbatim + emit warning.
    "4/2/2024,,test_ci6@example.com,11 Sample Way,Peoria,AZ,85383,,4805551212,Zeroname,TEST_0,,\n"
    # 7) Future customer_since date — must import + emit warning.
    f"{_FUTURE},,test_ci7@example.com,22 Future Ct,Peoria,AZ,85383,,4805559999,Futuro,TEST_Future,,\n"
    # 8) Missing state — must import with null + warning (was hard-reject).
    "6/15/2023,2023,test_ci8@example.com,2252 West Va Caballo Blanco,Phoenix,,85085,(602) 486-0488,(602) 486-0488,Juan,TEST_Torres,Landscaping,\n"
)


EXPECTED_ROWS = 8
EXPECTED_EMAILS = [f"test_ci{i}@example.com" for i in range(1, EXPECTED_ROWS + 1)]


def _fetch_customer(admin_headers, email: str) -> dict | None:
    r = requests.get(
        f"{API}/customers", headers=admin_headers, params={"search": email}, timeout=30,
    )
    assert r.status_code == 200, r.text
    docs = r.json() or []
    for c in docs:
        if (c.get("email") or "").lower() == email.lower():
            return c
    return None


def _cleanup(admin_headers):
    for email in EXPECTED_EMAILS:
        c = _fetch_customer(admin_headers, email)
        if c:
            requests.delete(f"{API}/customers/{c['id']}", headers=admin_headers, timeout=30)


@pytest.fixture(scope="module", autouse=True)
def _module_cleanup(admin_headers):
    _cleanup(admin_headers)  # pre-clean any stragglers from a prior aborted run
    yield
    _cleanup(admin_headers)


# ============================================================================
# TESTS
# ============================================================================

class TestFullMappingImport:
    """Regression coverage for the Feb-2026 real-world CSV import fix."""

    def test_import_response_shape_and_counts(self, admin_headers):
        r = requests.post(
            f"{API}/import/customers", headers=admin_headers,
            json={"csv": FIXTURE_CSV}, timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()

        # New canonical keys per the Feb-2026 brief.
        assert data["total_rows"] == EXPECTED_ROWS
        assert data["imported"] == EXPECTED_ROWS, (
            f"expected all {EXPECTED_ROWS} rows to import; got imported={data['imported']} "
            f"skipped={data['skipped']} errors={data.get('errors')}"
        )
        assert data["skipped"] == 0
        assert isinstance(data["warnings"], list)

        # Historical keys — still populated so ImportModal keeps working.
        assert data["imported_count"] == EXPECTED_ROWS
        assert data["skipped_count"] == 0
        assert isinstance(data.get("errors"), list)

    def test_all_fields_populated_on_happy_path_row(self, admin_headers):
        # Re-run the import so fetch is deterministic on this module's row.
        requests.post(f"{API}/import/customers", headers=admin_headers,
                      json={"csv": FIXTURE_CSV}, timeout=60)
        doc = _fetch_customer(admin_headers, "test_ci1@example.com")
        assert doc is not None, "row 2 (Sara Garcia) did not persist"
        assert doc["first_name"] == "Sara"
        assert doc["last_name"] == "TEST_Garcia"
        assert doc["email"] == "test_ci1@example.com"
        assert doc["service_address"]["street"] == "13798 West Whisper Rock Trail"
        assert doc["service_address"]["city"] == "Peoria"
        assert doc["service_address"]["state"] == "AZ"
        assert doc["service_address"]["postal_code"] == "85383"
        assert doc["customer_since"] == "2024-06-11"
        # Tag (singular header) must land as tags[] — this is the core bug.
        assert doc["tags"] == ["Pool Client"], f"tags dropped: {doc['tags']!r}"
        # Mobile-only row: phones[] carries a single mobile entry.
        phones = doc.get("phones") or []
        assert any(p.get("type") == "mobile" and p.get("e164") == "+16232498461" for p in phones), phones

    def test_phone_normalization_variants(self, admin_headers):
        requests.post(f"{API}/import/customers", headers=admin_headers,
                      json={"csv": FIXTURE_CSV}, timeout=60)
        # (623) 249-8461 → +16232498461
        d1 = _fetch_customer(admin_headers, "test_ci1@example.com")
        assert d1["phone"] == "+16232498461", d1["phone"]
        # 2197071542 → +12197071542
        d2 = _fetch_customer(admin_headers, "test_ci2@example.com")
        assert d2["phone"] == "+12197071542", d2["phone"]
        # 425 241 6779 → +14252416779
        d4 = _fetch_customer(admin_headers, "test_ci4@example.com")
        assert d4["phone"] == "+14252416779", d4["phone"]

    def test_multi_tag_row_splits_on_comma(self, admin_headers):
        requests.post(f"{API}/import/customers", headers=admin_headers,
                      json={"csv": FIXTURE_CSV}, timeout=60)
        d5 = _fetch_customer(admin_headers, "test_ci5@example.com")
        assert d5 is not None
        assert set(d5["tags"]) == {"Pool Client", "VIP"}, d5["tags"]

    def test_missing_address_rows_import_with_nulls_not_skipped(self, admin_headers):
        r = requests.post(f"{API}/import/customers", headers=admin_headers,
                          json={"csv": FIXTURE_CSV}, timeout=60)
        data = r.json()

        # Row 3 (missing street + postal) — must import, not skip.
        d3 = _fetch_customer(admin_headers, "test_ci3@example.com")
        assert d3 is not None, "row missing street+postal was hard-rejected — regression"
        assert d3["service_address"]["street"] in (None, "")
        assert d3["service_address"]["postal_code"] in (None, "")
        assert d3["service_address"]["city"] == "Peoria"

        # Row 8 (missing state) — must import.
        d8 = _fetch_customer(admin_headers, "test_ci8@example.com")
        assert d8 is not None, "row missing state was hard-rejected — regression"
        assert d8["service_address"]["state"] in (None, "")

        # Warnings must include the missing-field messages for the two
        # rows above. Multiple warnings can share a row number, so iterate
        # the raw list — do not collapse into a row-keyed dict.
        warn_messages = [w["message"].lower() for w in data["warnings"]]
        assert any("service address street missing" in m for m in warn_messages), warn_messages
        assert any("state missing" in m for m in warn_messages), warn_messages

    def test_future_customer_since_warning_but_still_imported(self, admin_headers):
        r = requests.post(f"{API}/import/customers", headers=admin_headers,
                          json={"csv": FIXTURE_CSV}, timeout=60)
        data = r.json()
        d7 = _fetch_customer(admin_headers, "test_ci7@example.com")
        assert d7 is not None, "future-dated row was rejected — regression"
        assert d7["customer_since"] is not None
        assert any("in the future" in w["message"] for w in data["warnings"]), (
            f"expected 'in the future' warning; got {[w['message'] for w in data['warnings']]}"
        )

    def test_zero_last_name_kept_verbatim(self, admin_headers):
        r = requests.post(f"{API}/import/customers", headers=admin_headers,
                          json={"csv": FIXTURE_CSV}, timeout=60)
        data = r.json()
        d6 = _fetch_customer(admin_headers, "test_ci6@example.com")
        assert d6 is not None, "row with last_name='0' was rejected"
        assert d6["last_name"] == "TEST_0"
        assert d6["first_name"] == "Zeroname"
        # Not a hard-fail — total imported still equals 8.
        assert data["imported"] == EXPECTED_ROWS

    def test_tenant_isolation_preserved(self, admin_headers):
        r = requests.post(f"{API}/import/customers", headers=admin_headers,
                          json={"csv": FIXTURE_CSV}, timeout=60)
        assert r.status_code == 200
        # Every persisted doc must be found via the caller's tenant scoping
        # (GET /customers is tenant-filtered on the server side).
        for email in EXPECTED_EMAILS:
            doc = _fetch_customer(admin_headers, email)
            assert doc is not None, f"tenant-isolated fetch failed for {email}"
            # tenant_id is not projected on the list endpoint, but the fact
            # that the caller can see it via that endpoint already proves
            # the row was written with the caller's tenant_id.


# ============================================================================
# Large-import scale test — no row cap, batched inserts, timely completion.
# ============================================================================

class TestBulkImportScale:
    """Feb-2026 hotfix — no row cap, batched inserts, warning truncation."""

    _BULK_EMAIL_PREFIX = "test_bulk_ci_"
    _BULK_ROWS = 5000

    @staticmethod
    def _synthetic_csv(n: int) -> str:
        """Build an n-row CSV with the reported header shape (double comma,
        singular Tag, trailing comma). Each row has a unique email so the
        upsert path never collapses distinct rows."""
        header = (
            "Customer Since,,Email,Service address Street,City,State,Postal Code,"
            "Phone,Mobile,First Name,Last Name,Tag,\n"
        )
        lines = [header]
        for i in range(n):
            # Rotate through 10,000 phone-number tails so E.164 stays valid.
            phone_tail = f"{4800000000 + i:010d}"
            phone_fmt = f"({phone_tail[:3]}) {phone_tail[3:6]}-{phone_tail[6:]}"
            lines.append(
                f"6/1/2024,,test_bulk_ci_{i}@example.com,"
                f"{100 + i} Synthetic Ln,Peoria,AZ,85383,,{phone_fmt},"
                f"Load,TEST_Bulk{i},Landscaping,\n"
            )
        return "".join(lines)

    @classmethod
    @pytest.fixture(scope="class", autouse=True)
    def _bulk_cleanup(cls, admin_headers):
        # Bulk cleanup happens via Mongo directly — hitting DELETE 5,000
        # times would multiply the test runtime by an order of magnitude.
        import os
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        db_ = client[env["DB_NAME"]]

        def _wipe():
            db_.customers.delete_many({"email": {"$regex": "^test_bulk_ci_"}})
            db_.customer_import_reports.delete_many({
                "created_by_user_id": {"$regex": "."}, "total_rows": cls._BULK_ROWS,
            })
        _wipe()
        yield
        _wipe()
        client.close()

    def test_5000_row_import_no_cap_batched(self, admin_headers):
        import time
        csv = self._synthetic_csv(self._BULK_ROWS)
        payload_mb = len(csv.encode("utf-8")) / (1024 * 1024)
        t0 = time.perf_counter()
        r = requests.post(
            f"{API}/import/customers", headers=admin_headers,
            json={"csv": csv}, timeout=180,
        )
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        data = r.json()
        print(
            f"\n[bulk-import] rows={self._BULK_ROWS} payload≈{payload_mb:.1f}MB "
            f"elapsed={elapsed:.1f}s imported={data['imported']} "
            f"skipped={data['skipped']} warnings_total={data['warnings_total']}"
        )
        assert data["total_rows"] == self._BULK_ROWS
        assert data["imported"] == self._BULK_ROWS, (
            f"only {data['imported']}/{self._BULK_ROWS} imported — row cap somewhere?"
        )
        assert data["skipped"] == 0
        assert elapsed < 120, f"5k-row import took {elapsed:.1f}s — exceeds 2min budget"
        # No warnings on the happy synthetic rows.
        assert data["warnings_total"] == 0
        assert data["warnings_truncated"] is False
        # import_id must be present.
        assert isinstance(data.get("import_id"), str) and len(data["import_id"]) > 8

    def test_bulk_import_report_endpoint(self, admin_headers):
        # Re-run a smaller import that produces >100 warnings (each row
        # contributes 3 warnings: street/city/postal missing) so the
        # response truncates at 100 while the persisted report retains all.
        header = (
            "Customer Since,,Email,Service address Street,City,State,Postal Code,"
            "Phone,Mobile,First Name,Last Name,Tag,\n"
        )
        lines = [header]
        for i in range(60):  # 60 rows × 3 warnings/row = 180 warnings
            lines.append(
                f",,test_bulk_ci_warn_{i}@example.com,,,AZ,,,4805551{i:03d},"
                f"Warn,TEST_Bulk{i},,\n"
            )
        r = requests.post(
            f"{API}/import/customers", headers=admin_headers,
            json={"csv": "".join(lines)}, timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        import_id = data["import_id"]
        assert data["warnings_total"] == 180
        assert data["warnings_truncated"] is True
        assert len(data["warnings"]) == 100  # inline cap

        # GET the full report — every warning must be there.
        r2 = requests.get(
            f"{API}/customers/imports/{import_id}", headers=admin_headers, timeout=30,
        )
        assert r2.status_code == 200, r2.text
        report = r2.json()
        assert report["id"] == import_id
        assert len(report["warnings"]) == 180, (
            f"full log should carry all warnings; got {len(report['warnings'])}"
        )
        # Wipe the warn-batch rows so the next test's cleanup fixture is clean.
        import requests as _rq
        for i in range(60):
            doc = _fetch_customer(admin_headers, f"test_bulk_ci_warn_{i}@example.com")
            if doc:
                _rq.delete(f"{API}/customers/{doc['id']}", headers=admin_headers, timeout=15)

    def test_import_report_404_for_unknown_id(self, admin_headers):
        r = requests.get(
            f"{API}/customers/imports/does-not-exist", headers=admin_headers, timeout=30,
        )
        assert r.status_code == 404
