import time
import base64
import hashlib
import requests
from settings import (
NUVEI_APP_CODE_SERVER,
NUVEI_APP_KEY_SERVER,
NUVEI_BASE_URL,
)




class NuveiClient:
"""Cliente real de Nuvei LinkToPay"""


def __init__(self):
self.base_url = NUVEI_BASE_URL


def generate_auth_token(self) -> str:
ts = str(int(time.time()))
uniq = NUVEI_APP_KEY_SERVER + ts
hashed = hashlib.sha256(uniq.encode()).hexdigest()
raw = f"{NUVEI_APP_CODE_SERVER};{ts};{hashed}"
return base64.b64encode(raw.encode()).decode()


def create_linktopay(self, payload: dict) -> dict:
url = f"{self.base_url}/linktopay/init_order/"


headers = {
"Content-Type": "application/json",
"Auth-Token": self.generate_auth_token(),
}


response = requests.post(url, json=payload, headers=headers, timeout=30)
try:
data = response.json()
except Exception:
raise Exception(f"Invalid response from Nuvei: {response.text}")


if not data.get("success", False):
raise Exception(f"Nuvei Error: {data.get('detail')}")


return data