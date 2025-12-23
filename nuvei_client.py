# ============================================================
# nuvei_client.py — Cliente HTTP Nuvei LinkToPay (Ecuador)
# PITIUPI v6.0 — Motor de Comunicación con Nuvei
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
        
        Args:
            order_data: Payload completo según spec Nuvei
        
        Returns:
            dict: Respuesta normalizada V6
                {
                    "success": bool,
                    "data": dict | None,      # Respuesta Nuvei si success=True
                    "detail": str | None,     # Mensaje de error si success=False
                    "raw": str | None         # Response.text si hay error
                }
        """
        url = f"{self.base_url}/linktopay/init_order/"
        
        headers = {
            "Content-Type": "application/json",
            "Auth-Token": self._generate_auth_token(),
        }

        logger.info(f"➡️  POST {url}")
        logger.debug("📦 Payload LinkToPay preparado")

        # ============================================================
        # REQUEST HTTP
        # ============================================================
        try:
            response = requests.post(
                url,
                json=order_data,
                headers=headers,
                timeout=15,  # Timeout fail-fast (15 segundos)
            )

        except requests.exceptions.Timeout:
            logger.error("❌ Timeout al conectar con Nuvei (15s)")
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
            logger.error("❌ Error inesperado en request", exc_info=True)
            return {
                "success": False,
                "data": None,
                "detail": "Error inesperado llamando a Nuvei",
                "raw": None,
            }

        # ============================================================
        # MANEJO DE STATUS CODES
        # ============================================================

        # 5xx: Error interno de Nuvei
        if response.status_code >= 500:
            logger.error(f"❌ Error interno Nuvei: {response.status_code}")
            return {
                "success": False,
                "data": None,
                "detail": f"Error interno de Nuvei ({response.status_code})",
                "raw": response.text,
            }

        # 401: Auth-Token inválido o expirado
        if response.status_code == 401:
            logger.error("❌ Auth-Token inválido (401)")
            return {
                "success": False,
                "data": None,
                "detail": "Auth-Token inválido o expirado",
                "raw": response.text,
            }

        # 400 / 403: Payload inválido o rechazado
        if response.status_code in (400, 403):
            logger.error(f"❌ Request rechazado ({response.status_code})")
            return {
                "success": False,
                "data": None,
                "detail": f"Solicitud rechazada por Nuvei ({response.status_code})",
                "raw": response.text,
            }

        # ============================================================
        # PARSEO DE JSON
        # ============================================================

        data = self._safe_json(response)
        
        if not data:
            logger.error("❌ Respuesta Nuvei no es JSON válido")
            return {
                "success": False,
                "data": None,
                "detail": "Respuesta Nuvei inválida (no JSON)",
                "raw": response.text,
            }

        # Verificar campo "success" en la respuesta
        if "success" not in data:
            logger.error("❌ Respuesta sin campo 'success'")
            return {
                "success": False,
                "data": None,
                "detail": "Respuesta Nuvei malformada",
                "raw": response.text,
            }

        # ============================================================
        # RESPUESTA EXITOSA
        # ============================================================

        if data.get("success") is True:
            logger.info("✅ LinkToPay creado exitosamente")
            logger.info(f"🆔 Order ID: {data.get('order', {}).get('id', 'N/A')}")
            return {
                "success": True,
                "data": data,
                "detail": None,
                "raw": None,
            }

        # ============================================================
        # RESPUESTA CON ERROR REPORTADO POR NUVEI
        # ============================================================

        error_detail = data.get("detail") or data.get("error", {}).get("type") or "Error reportado por Nuvei"
        logger.error(f"❌ Nuvei reportó error: {error_detail}")
        
        return {
            "success": False,
            "data": None,
            "detail": error_detail,
            "raw": str(data),
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


# ============================================================
# END OF FILE
# ============================================================
