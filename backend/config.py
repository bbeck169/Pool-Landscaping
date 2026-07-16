from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import os
import logging

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-change-me')
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
