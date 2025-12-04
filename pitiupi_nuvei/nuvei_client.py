import base64
import hmac
import hashlib
import time
import requests
import logging
from typing import Dict, Any
import os

logger = logging.getLogger(__name__)


class NuveiClient:
    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        self.app_code = app_code
        self.app_key = app_key
        self.environment = environment

        if environment == "prod":
            self.base_url = "https://noccapi.paymentez.com"
        else:
            self.base_url = "https://noccapi-stg.paymentez.com"

        logger.info(f"🌐 NuveiClient iniciado en {environment}")
        logger.info(f"🔑 Base URL: {self.base_url}")

    def generate_auth_token(self) -> str:
        """
        Nuvei Ecuador (PROD) - Auth Token oficial:

        raw = APP_CODE + ";" + timestamp + ";" + sha256(APP_KEY + timestamp)
        token = Base64(raw)
        """
        import time
        import hashlib
        import base64

        timestamp = str(int(time.time()))

        # uniq_string = secret-key + timestamp
        uniq_string = self.app_key + timestamp

        # uniq_hash = sha256(uniq_string).hexdigest()
        uniq_hash = hashlib.sha256(uniq_string.encode()).hexdigest()

        # raw token = app_code ; timestamp ; uniq_hash
        raw_token = f"{self.app_code};{timestamp};{uniq_hash}"

        # final token = base64(raw_token)
        auth_token = base64.b64encode(raw_token.encode()).decode()

        return auth_token


    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/linktopay/init_order/"

        try:
            headers = {
                "Content-Type": "application/json",
                "Auth-Token": self.generate_auth_token()
            }

            logger.info(f"➡ POST {url}")
            logger.info(f"➡ Payload: {order_data}")

            resp = requests.post(url, json=order_data, headers=headers, timeout=30)

            # Intentamos parsear JSON
            try:
                data = resp.json()
            except:
                logger.error(f"❌ Nuvei devolvió HTML o no-JSON ({resp.status_code}): {resp.text}")
                return {"success": False, "detail": "Respuesta no JSON de Nuvei", "raw": resp.text}

            logger.info(f"🔄 Respuesta JSON Nuvei: {data}")
            return data

        except Exception as e:
            logger.error(f"❌ Error Nuvei: {e}", exc_info=True)
            return {"success": False, "detail": str(e)}
