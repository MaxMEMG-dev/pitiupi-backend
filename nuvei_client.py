# ============================================================
# nuvei_client.py — 
# PITIUPI v5.1 — PRODUCCIÓN
# ============================================================

import base64
import hashlib
import time
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class NuveiClient:
    """
    Cliente oficial y robusto para Nuvei LinkToPay (Ecuador)
    - Autenticación Auth-Token
    - Validación estricta de errores HTTP
    - Soporta JSON inválido o HTML erróneo
    - Logs de diagnóstico completos
    """

    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        self.app_code = app_code
        self.app_key = app_key

        if environment == "prod":
            self.base_url = "https://noccapi.paymentez.com"
        else:
            self.base_url = "https://noccapi-stg.paymentez.com"

        logger.info(f"🌐 NuveiClient iniciado en entorno='{environment}'")
        logger.info(f"🔑 Base URL: {self.base_url}")

    # ---------------------------------------------------------
    # 🔐 GENERAR AUTH TOKEN (OFICIAL)
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
        logger.info(f"➡ Payload enviado: {order_data}")

        # -----------------------------
        # INTENTAR CONEXIÓN
        # -----------------------------
        try:
            response = requests.post(url, json=order_data, headers=headers, timeout=30)

        except requests.exceptions.Timeout:
            logger.error("❌ ERROR: Timeout conectando a Nuvei")
            return {
                "success": False,
                "detail": "Timeout al conectar con Nuvei"
            }

        except Exception as e:
            logger.error(f"❌ Error de conexión con Nuvei: {e}", exc_info=True)
            return {"success": False, "detail": f"Error de conexión: {e}"}

        # -----------------------------
        # MANEJO DE STATUS CODES
        # -----------------------------
        if response.status_code >= 500:
            logger.error(f"❌ Nuvei error 500: {response.text}")
            return {
                "success": False,
                "detail": "Error interno de Nuvei (500)",
                "raw": response.text
            }

        if response.status_code == 401:
            logger.error("❌ Auth-Token inválido (401)")
            return {"success": False, "detail": "Auth-Token inválido (401)"}

        if response.status_code == 400:
            logger.error(f"❌ Error 400 — Payload inválido: {response.text}")
            parsed = self._safe_json(response)
            return {
                "success": False,
                "detail": "Payload inválido (400)",
                "error": parsed,
                "raw": response.text
            }

        # -----------------------------
        # PROCESAR RESPUESTA
        # -----------------------------
        data = self._safe_json(response)

        if data is None:
            logger.error(f"❌ Respuesta Nuvei no es JSON válido: {response.text}")
            return {
                "success": False,
                "detail": "Nuvei devolvió una respuesta no JSON",
                "raw": response.text,
            }

        logger.info(f"🔄 Respuesta JSON Nuvei: {data}")

        # -----------------------------
        # VALIDAR ESTRUCTURA MÍNIMA
        # -----------------------------
        if not isinstance(data, dict) or "success" not in data:
            logger.error(f"❌ Respuesta Nuvei inválida, falta 'success': {data}")
            return {
                "success": False,
                "detail": "Respuesta Nuvei inválida (falta 'success')",
                "raw": data
            }

        return data

    # ---------------------------------------------------------
    # UTILIDAD: Parseo seguro de JSON
    # ---------------------------------------------------------
    def _safe_json(self, response):
        """Intenta convertir a JSON. Si falla, retorna None."""
        try:
            return response.json()
        except Exception:
            return None

