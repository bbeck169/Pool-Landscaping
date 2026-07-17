"""Shared pytest fixtures + session teardown that self-cleans test-created data.

All test suites create documents tagged with a ``TEST_`` prefix (titles, names,
subjects, etc.) and sign up throwaway accounts on ``@example.com``. This session
-scoped, autouse fixture removes those artifacts directly from MongoDB once the
whole test run finishes, so repeated runs don't accumulate seed data in the app's
list screens (jobs, leads, customers, etc.).
"""
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

# Load Mongo connection from the backend .env (tests run against the same DB the API uses)
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")

# Regex matching the TEST_ prefix used by every suite when creating fixtures.
_TEST_PREFIX = {"$regex": "^TEST_"}
_EXAMPLE_EMAIL = {"$regex": "example.com$"}

# collection -> query selecting only test-created docs (never seed/demo data)
_CLEANUP = {
    "jobs": {"$or": [{"title": _TEST_PREFIX}, {"title": {"$regex": " Request$"}}]},
    "quotes": {"$or": [{"title": _TEST_PREFIX}, {"billing_plan_id": {"$exists": True}}]},
    "leads": {"name": _TEST_PREFIX},
    "customers": {"$or": [{"name": _TEST_PREFIX}, {"email": _EXAMPLE_EMAIL}]},
    "users": {"email": _EXAMPLE_EMAIL},
    "billing_plans": {"service": _TEST_PREFIX},
    "repairs": {"$or": [{"equipment": _TEST_PREFIX}, {"issue": _TEST_PREFIX}]},
    "forms": {"name": _TEST_PREFIX},
    "automations": {"name": _TEST_PREFIX},
    "campaigns": {"subject": _TEST_PREFIX},
    "reviews": {"$or": [{"customer_name": _TEST_PREFIX}, {"text": _TEST_PREFIX}]},
    "checkins": {"$or": [{"note": _TEST_PREFIX}, {"address": _TEST_PREFIX}]},
    "items": {"name": _TEST_PREFIX},
    "rank_grid": {"keyword": _TEST_PREFIX},
    "workstream_events": {"payload.note": {"$regex": "^TEST_"}},
    "checks": {"payee_name_snapshot": {"$regex": "^TEST_"}},
    "expense_categories": {"transaction_id": {"$regex": "^TEST-"}},
    "cfo_llm_usage": {"tenant_id": {"$regex": "TEST_"}},
    "cfo_qna_history": {"actor_user_id": {"$regex": "^TEST-"}},
    "cfo_scenarios": {"actor_user_id": {"$regex": "^TEST-"}},
    "customer_churn_scores": {"customer_id": {"$regex": "^TEST-|^TEST_"}},
    "retention_campaign_targets": {"customer_ids": {"$elemMatch": {"$regex": "^TEST-|^TEST_"}}},
    "marketing_campaigns": {"goal": {"$regex": "at-risk|retention.*TEST", "$options": "i"}},
    "idempotency_keys": {"tenant_id": {"$regex": "TEST_|^TEST-"}},
    "users": {"email": {"$regex": "^TEST_dedup_|^TEST_solo_|^test-pool-tech@"}},
    "technicians": {"id": {"$regex": "^TEST-tech"}},
    "training_modules": {"$or": [{"code": {"$regex": "^test_", "$options": "i"}}, {"code": "test_system_immutable"}]},
    "training_progress": {"module_code": {"$regex": "^test_|^cpo-prep$", "$options": "i"}},
    "training_quiz_attempts": {"module_code": {"$regex": "^test_|^cpo-prep$", "$options": "i"}},
    "training_certificates": {"module_code": {"$regex": "^test_|^cpo-prep$", "$options": "i"}},
}


def _purge_test_data():
    if not (_MONGO_URL and _DB_NAME):
        return {}
    client = MongoClient(_MONGO_URL)
    try:
        db = client[_DB_NAME]
        removed = {}
        for coll, query in _CLEANUP.items():
            res = db[coll].delete_many(query)
            if res.deleted_count:
                removed[coll] = res.deleted_count
        # Notifications and form submissions that reference deleted test jobs/leads
        db["notifications"].delete_many({"title": _TEST_PREFIX})
        db["form_submissions"].delete_many({"values.name": _TEST_PREFIX})
        return removed
    finally:
        client.close()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data():
    """Runs once per test session; purges TEST_-tagged data after all tests finish."""
    yield
    removed = _purge_test_data()
    if removed:
        print(f"\n[conftest teardown] Purged test data: {removed}")
    else:
        print("\n[conftest teardown] No test data to purge.")
