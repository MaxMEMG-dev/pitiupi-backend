import os


NUVEI_APP_CODE_SERVER = os.getenv("NUVEI_APP_CODE_SERVER", "")
NUVEI_APP_KEY_SERVER = os.getenv("NUVEI_APP_KEY_SERVER", "")
NUVEI_ENVIRONMENT = os.getenv("NUVEI_ENV", "stg") # stg | prod


NUVEI_BASE_URL = (
"https://noccapi-stg.paymentez.com" if NUVEI_ENVIRONMENT == "stg"
else "https://noccapi.paymentez.com"
)


DATABASE_URL = os.getenv("DATABASE_URL", "")
