# ============================================================
# nuvei_client.py — Cliente HTTP Nuvei LinkToPay (Ecuador)
# PITIUPI v6.2 — Motor de Comunicación con Nuvei (Enhanced Logging)
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
    Cliente HTTP para Nuvei LinkToPay (Ecuador - STG/PROD)
    
    Responsabilidades:
    - Generar Auth-Token según especificación oficial Nuvei
    - Realizar POST a /linktopay/init_order/
    - Normalizar respuestas exitosas y de error
    - Manejo robusto de timeouts y errores HTTP
    - **LOGGING COMPLETO DE ERRORES 400/403**
    
    NO hace:
    - Lógica de negocio
    - Validaciones financieras
    - Acceso a base de datos
    - Decisiones sobre pagos
    """

    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        """
        Inicializa cliente Nuvei
        
        Args:
            app_code: Application Code de Nuvei
            app_key: Secret Key de Nuvei
            environment: "stg" o "prod"
        """
        self.app_code = app_code
        self.app_key = app_key

        # URLs oficiales Nuvei Ecuador
        if environment == "prod":
            self.base_url = "https://noccapi.paymentez.com"
        else:
            self.base_url = "https://noccapi-stg.paymentez.com"

        logger.info(f"🌐 NuveiClient inicializado")
        logger.info(f"🔧 Entorno: {environment}")
        logger.info(f"🔗 Base URL: {self.base_url}")

    # ============================================================
    # AUTENTICACIÓN NUVEI (OFICIAL)
    # ============================================================

    def _generate_auth_token(self) -> str:
        """
        Genera Auth-Token según especificación oficial Nuvei:
        
        1. unix_timestamp (segundos, UTC)
        2. uniq_token_hash = SHA256(app_key + timestamp)
        3. raw_string = "app_code;timestamp;uniq_token_hash"
        4. auth_token = Base64(raw_string)
        
        Returns:
            str: Token en formato Base64
        """
        # Timestamp en SEGUNDOS (UTC)
        unix_timestamp = str(int(time.time()))
        
        # Hash SHA256 del app_key + timestamp
        uniq_token_string = self.app_key + unix_timestamp
        uniq_token_hash = hashlib.sha256(uniq_token_string.encode()).hexdigest()
        
        # Construir string raw: app_code;timestamp;hash
        raw_string = f"{self.app_code};{unix_timestamp};{uniq_token_hash}"
        
        # Encodear a Base64
        auth_token = base64.b64encode(raw_string.encode()).decode()
        
        logger.debug(f"🔐 Auth-Token generado | timestamp={unix_timestamp}")
        return auth_token

    # ============================================================
    # LINKTOPAY - CREACIÓN DE ORDEN
    # ============================================================

    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Crea orden LinkToPay en Nuvei (Ecuador)

    Returns:
        dict:
        {
            "success": bool,
            "data": {
                "order": {...},
                "payment": {...},
                "billing_address": {...}
            } | None,
            "detail": str | None,
            "raw": str | None
        }
    """
    url = f"{self.base_url}/linktopay/init_order/"

    headers = {
        "Content-Type": "application/json",
        "Auth-Token": self._generate_auth_token(),
    }

    logger.info(f"➡️  POST {url}")
    logger.debug(f"📦 Payload enviado a Nuvei: {order_data}")

    # ============================================================
    # REQUEST HTTP
    # ============================================================
    try:
        response = requests.post(
            url,
            json=order_data,
            headers=headers,
            timeout=15,
        )
    except requests.exceptions.Timeout:
        logger.error("❌ Timeout al conectar con Nuvei (15s)")
        return {"success": False, "data": None, "detail": "Timeout Nuvei", "raw": None}
    except Exception as e:
        logger.error("❌ Error inesperado llamando a Nuvei", exc_info=True)
        return {"success": False, "data": None, "detail": str(e), "raw": None}

    # ============================================================
    # STATUS CODES
    # ============================================================
    if response.status_code >= 500:
        logger.error(f"❌ Error interno Nuvei {response.status_code}")
        logger.error(response.text[:1000])
        return {
            "success": False,
            "data": None,
            "detail": "Error interno Nuvei",
            "raw": response.text,
        }

    if response.status_code in (400, 401, 403):
        logger.error("=" * 60)
        logger.error(f"❌ REQUEST RECHAZADO POR NUVEI ({response.status_code})")
        logger.error(response.text[:1000])
        logger.error("=" * 60)
        return {
            "success": False,
            "data": None,
            "detail": f"Solicitud rechazada por Nuvei ({response.status_code})",
            "raw": response.text,
        }

    # ============================================================
    # PARSEO JSON
    # ============================================================
    try:
        payload = response.json()
    except Exception:
        logger.error("❌ Respuesta Nuvei no es JSON válido")
        logger.error(response.text[:1000])
        return {
            "success": False,
            "data": None,
            "detail": "Respuesta Nuvei inválida",
            "raw": response.text,
        }

    # ============================================================
    # RESPUESTA EXITOSA
    # ============================================================
    if payload.get("success") is True:
        logger.info("✅ LinkToPay creado exitosamente")

        nuvei_data = payload.get("data", {})

        order = nuvei_data.get("order")
        payment = nuvei_data.get("payment")

        logger.info("=" * 60)
        logger.info("📊 RESPUESTA NORMALIZADA DE NUVEI")
        logger.info(f"🆔 Order ID: {order.get('id') if order else 'N/A'}")
        logger.info(f"🔗 Payment URL: {payment.get('payment_url') if payment else 'N/A'}")
        logger.info("=" * 60)

        return {
            "success": True,
            "data": nuvei_data,
            "detail": None,
            "raw": None,
        }

    # ============================================================
    # ERROR REPORTADO POR NUVEI
    # ============================================================
    logger.error("❌ Nuvei respondió success=False")
    logger.error(payload)

    return {
        "success": False,
        "data": None,
        "detail": payload.get("detail", "Error Nuvei"),
        "raw": str(payload),
    }

    # ============================================================
    # UTILIDADES
    # ============================================================

    def _safe_json(self, response) -> Optional[Dict[str, Any]]:
        """
        Intenta parsear response.json() de forma segura
        
        Returns:
            dict si es JSON válido, None si falla
        """
        try:
            return response.json()
        except Exception as e:
            logger.error(f"❌ Error parseando JSON: {e}")
            return None


