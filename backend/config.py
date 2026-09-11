from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
import logging

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url, maxPoolSize=50)
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
