from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
import logging

ROOT_DIR = Path(__file__).parent
# Feb-2026 · Payments env hardening —
# ``override=False`` is python-dotenv's default, but writing it
# explicitly protects against a future refactor accidentally flipping
# it: the pod's PROCESS ENVIRONMENT must always win over any
# committed ``.env`` file for secrets like ``STRIPE_SECRET_KEY_LIVE``
# and ``JWT_SECRET``. Ops rotates those independently of the repo.
#
# We deliberately load ONLY ``.env`` here — ``.env.bak.*``,
# ``.env.local``, ``.env.production.example``, and ``.env.example`` are
# intentionally excluded from the runtime search path (see
# ``services.env_guard.DOTENV_EXCLUSION_GLOBS``). Backup / example
# files must never be authoritative for secrets.
load_dotenv(ROOT_DIR / '.env', override=False)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
# Phase P37.1 · Feb-2026 — Mongo pool config cleanup.
#
# Single source of truth: the kwargs on this ``AsyncIOMotorClient``
# call. ``MONGO_URL`` (see ``backend/.env``) intentionally carries
# ZERO query-string params — audit-grep confirmed no duplicate
# ``maxPoolSize`` etc. If a future secret rotation reintroduces a
# ``?maxPoolSize=`` on the URL, the Motor kwarg below still wins
# (Motor's kwarg takes precedence over the URL query string), but
# ops should keep the URL cosmetically clean per the P37.1 brief.
#
# ``maxPoolSize=300`` — preserved from pre-P37.1 (deliberate high-
# concurrency budget for the API-heavy multi-tenant workload; do NOT
# drop to Motor's default 100 without a load-test).
#
# ``serverSelectionTimeoutMS=5000`` — new in P37.1. Motor's default
# is 30_000 which meant a transient Atlas hiccup blocked boot for
# 30s on every fresh pod spin-up. 5s is the accepted-practice guard
# for a healthy Atlas region.
_MONGO_MAX_POOL_SIZE = 300
_MONGO_SERVER_SELECTION_TIMEOUT_MS = 5000
client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=_MONGO_MAX_POOL_SIZE,
    serverSelectionTimeoutMS=_MONGO_SERVER_SELECTION_TIMEOUT_MS,
)
db = client[os.environ['DB_NAME']]

# SEC-P3-3 hotfix — fail loud if JWT_SECRET is missing / weak. Previously
# this had a public default fallback string; production must provide a
# real secret via env.
_APP_ENV = os.environ.get("APP_ENV", "preview").lower()
JWT_SECRET = os.environ.get("JWT_SECRET", "")
if _APP_ENV == "production":
    if not JWT_SECRET or len(JWT_SECRET) < 32:
        raise RuntimeError(
            "JWT_SECRET must be set (>=32 chars) in production. "
            "Refusing to boot with an unset or weak signing secret."
        )
elif not JWT_SECRET:
    # Dev/preview convenience: emit a random per-boot secret + warn.
    import secrets as _sec
    JWT_SECRET = _sec.token_urlsafe(48)
    logging.getLogger("pool_crm").warning(
        "JWT_SECRET unset — using per-boot random secret (dev/preview only)"
    )
JWT_ALGO = 'HS256'
TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')
APP_PUBLIC_URL = os.environ.get('APP_PUBLIC_URL', '').rstrip('/')
OPENWEB_NINJA_API_KEY = (os.environ.get('OPENWEB_NINJA_ZILLOW_API_KEY')
                          or os.environ.get('OPENWEB_NINJA_API_KEY', ''))
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pool_crm")

# Phase P37.1 · Feb-2026 — one-shot startup log so ops can grep the
# effective pool config from pod logs at boot. Line format:
#   [mongo] maxPoolSize=300 serverSelectionTimeoutMS=5000 (source=code)
logger.info(
    "[mongo] maxPoolSize=%s serverSelectionTimeoutMS=%s (source=code)",
    _MONGO_MAX_POOL_SIZE, _MONGO_SERVER_SELECTION_TIMEOUT_MS,
)

# Feb-2026 · Payments env hardening — placeholder-shape guard on
# ``STRIPE_SECRET_KEY_LIVE``. Runs once at module load so the LOUD log
# line lands at boot. Ops greps for ``STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED``
# in pod logs. The guard NEVER raises — an empty key is legitimate in
# preview / test pods, and a real payment call will surface a Stripe
# 401 anyway. This is purely a diagnostic hint.
try:
    from services.env_guard import check_stripe_live_key
    check_stripe_live_key(logger=logger)
except Exception as _guard_exc:  # pragma: no cover — never break boot
    logger.warning(
        "env_guard.check_stripe_live_key skipped: %s", _guard_exc,
    )
