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
        PRODUCCIÓN Ecuador → Firma HMAC-SHA512(app_key como key, message=app_code+nonce+app_key)
        """
        nonce = str(int(time.time()))
        message = f"{self.app_code}{nonce}{self.app_key}"
        auth_hash = hmac.new(
            key=self.app_key.encode(),
            msg=message.encode(),
            digestmod=hashlib.sha512
        ).hexdigest()

        token = f"{self.app_code};{nonce};{auth_hash}"
        auth_token_b64 = base64.b64encode(token.encode()).decode()

        logger.info(f"🔐 Auth-Token generado")
        return auth_token_b64

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
