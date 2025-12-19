# ============================================================
# nuvei_client.py — Cliente HTTP externo para Nuvei LinkToPay
# PITIUPI v6.0 — PRODUCCIÓN
# Cliente HTTP externo (NO lógica de negocio)
# ============================================================

import base64
import hashlib
import time
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class NuveiClient:
    """
    V6: Cliente HTTP para Nuvei LinkToPay (Ecuador)

    Responsabilidades:
    - Generar Auth-Token según especificación Nuvei
    - Hacer requests HTTP a API de Nuvei
    - Normalizar respuestas (success/error)
    - Manejo robusto de errores HTTP

    NO hace:
    - ❌ Lógica de negocio
    - ❌ Validaciones financieras
    - ❌ Acceso a base de datos
    - ❌ Mutación de estado
    - ❌ Decisiones de pago

    Características:
    - Stateless
    - Thread-safe
    - Fail-fast
    """

    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        self.app_code = app_code
        self.app_key = app_key

        if environment == "prod":
            self.base_url = "https://noccapi.paymentez.com"
        else:
            self.base_url = "https://noccapi-stg.paymentez.com"

        logger.info(f"🌐 NuveiClient inicializado | env={environment}")
        logger.info(f"🔑 Base URL: {self.base_url}")

    # ============================================================
    # AUTENTICACIÓN
    # ============================================================

    def generate_auth_token(self) -> str:
        """
        Auth-Token Nuvei (oficial):

        raw = app_code;timestamp;SHA256(app_key + timestamp)
        token = Base64(raw)
        """
        timestamp = str(int(time.time()))
        uniq_hash = hashlib.sha256(
            (self.app_key + timestamp).encode()
        ).hexdigest()

        raw = f"{self.app_code};{timestamp};{uniq_hash}"
        return base64.b64encode(raw.encode()).decode()

    # ============================================================
    # LINKTOPAY
    # ============================================================

    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crea orden LinkToPay en Nuvei (STG / PROD)

        Retorna estructura V6 normalizada:
        {
            success: bool,
            data: dict | None,
            detail: str | None,
            raw: str | None
        }
        """
        url = f"{self.base_url}/linktopay/init_order/"

        headers = {
            "Content-Type": "application/json",
            "Auth-Token": self.generate_auth_token(),
        }

        logger.info(f"➡ POST {url}")
        logger.debug("➡ Payload LinkToPay enviado a Nuvei")

        try:
            response = requests.post(
                url,
                json=order_data,
                headers=headers,
                timeout=10,  # segundos (fail-fast real)
            )

        except requests.exceptions.Timeout:
            logger.error("❌ Timeout conectando a Nuvei (10s)")
            return {
                "success": False,
                "data": None,
                "detail": "Timeout al conectar con Nuvei",
                "raw": None,
            }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Error de conexión con Nuvei: {e}")
            return {
                "success": False,
                "data": None,
                "detail": "Error de conexión con Nuvei",
                "raw": None,
            }

        except Exception as e:
            logger.error("❌ Error inesperado llamando a Nuvei", exc_info=True)
            return {
                "success": False,
                "data": None,
                "detail": "Error inesperado llamando a Nuvei",
                "raw": None,
            }

        # ============================================================
        # STATUS CODES
        # ============================================================

        if response.status_code >= 500:
            return {
                "success": False,
                "data": None,
                "detail": f"Error interno de Nuvei ({response.status_code})",
                "raw": response.text,
            }

        if response.status_code == 401:
            return {
                "success": False,
                "data": None,
                "detail": "Auth-Token inválido (401)",
                "raw": response.text,
            }

        if response.status_code in (400, 403):
            return {
                "success": False,
                "data": None,
                "detail": "Solicitud rechazada por Nuvei",
                "raw": response.text,
            }

        # ============================================================
        # JSON
        # ============================================================

        data = self._safe_json(response)
        if not data or "success" not in data:
            return {
                "success": False,
                "data": None,
                "detail": "Respuesta Nuvei inválida",
                "raw": response.text,
            }

        if data.get("success") is True:
            return {
                "success": True,
                "data": data,
                "detail": None,
                "raw": None,
            }

        return {
            "success": False,
            "data": None,
            "detail": data.get("detail") or "Error reportado por Nuvei",
            "raw": str(data),
        }

    # ============================================================
    # UTIL
    # ============================================================

    def _safe_json(self, response) -> Optional[Dict[str, Any]]:
        try:
            return response.json()
        except Exception:
            return None
