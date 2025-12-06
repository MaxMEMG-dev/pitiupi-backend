import base64
import hashlib
import time
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class NuveiClient:
    """
    Cliente oficial para consumir Nuvei LinkToPay (Ecuador)
    Incluye:
    - Generación del Auth-Token
    - Manejo de errores HTTP
    - Parseo seguro de JSON
    - Logs completos
    """

    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        self.app_code = app_code
        self.app_key = app_key

        if environment == "prod":
            self.base_url = "https://noccapi.paymentez.com"
        else:
            self.base_url = "https://noccapi-stg.paymentez.com"

        logger.info(f"🌐 NuveiClient iniciado en '{environment}'")
        logger.info(f"🔑 Base URL: {self.base_url}")

    # ---------------------------------------------------------
    # 🔐 GENERAR AUTH TOKEN (OFICIAL NUVEI)
    # ---------------------------------------------------------
    def generate_auth_token(self) -> str:
        timestamp = str(int(time.time()))

        uniq_string = self.app_key + timestamp
        uniq_hash = hashlib.sha256(uniq_string.encode()).hexdigest()

        raw = f"{self.app_code};{timestamp};{uniq_hash}"
        token = base64.b64encode(raw.encode()).decode()

        return token

    # ---------------------------------------------------------
    # 🔗 CREAR LINKTOPAY
    # ---------------------------------------------------------
    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/linktopay/init_order/"

        headers = {
            "Content-Type": "application/json",
            "Auth-Token": self.generate_auth_token()
        }

        logger.info(f"➡ POST {url}")
        logger.info(f"➡ Headers: {headers}")
        logger.info(f"➡ Payload: {order_data}")

        try:
            response = requests.post(url, json=order_data, headers=headers, timeout=30)
        except Exception as e:
            logger.error(f"❌ Error de conexión con Nuvei: {e}", exc_info=True)
            return {"success": False, "detail": f"Error de conexión: {e}"}

        # ---------------------------------------------------------
        # 🛑 Validar códigos HTTP
        # ---------------------------------------------------------
        if response.status_code >= 500:
            logger.error(f"❌ Nuvei error 500: {response.text}")
            return {"success": False, "detail": "Error interno de Nuvei (500)", "raw": response.text}

        if response.status_code == 401:
            logger.error("❌ Auth-Token inválido")
            return {"success": False, "detail": "Auth-Token inválido (401)"}

        if response.status_code == 400:
            logger.error(f"❌ Error 400 — Payload inválido: {response.text}")
            return {"success": False, "detail": f"Payload inválido (400)", "raw": response.text}

        # ---------------------------------------------------------
        # 📦 Parsear JSON o detectar HTML
        # ---------------------------------------------------------
        try:
            data = response.json()
        except Exception:
            logger.error(f"❌ Nuvei devolvió HTML/no-JSON: {response.text}")
            return {
                "success": False,
                "detail": "Nuvei devolvió una respuesta no JSON",
                "raw": response.text,
            }

        logger.info(f"🔄 Respuesta JSON Nuvei: {data}")

        # ---------------------------------------------------------
        # 🧪 Validar formato mínimo
        # ---------------------------------------------------------
        if "success" not in data:
            logger.error("❌ La respuesta no contiene 'success'")
            return {
                "success": False,
                "detail": "Respuesta Nuvei inválida (falta success)",
                "raw": data,
            }

        return data
