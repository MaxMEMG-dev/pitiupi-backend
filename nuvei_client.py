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
        
        Args:
            order_data: Payload completo según spec Nuvei
        
        Returns:
            dict: Respuesta normalizada V6.2
                {
                    "success": bool,
                    "data": dict | None,      # Respuesta Nuvei si success=True
                    "detail": str | None,     # Mensaje de error si success=False
                    "raw": str | None         # Response.text si hay error (MEJORADO)
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
            logger.error(f"❌ Body: {response.text[:1000]}")
            return {
                "success": False,
                "data": None,
                "detail": f"Error interno de Nuvei ({response.status_code})",
                "raw": response.text,
            }

        # 401: Auth-Token inválido o expirado
        if response.status_code == 401:
            logger.error("❌ Auth-Token inválido (401)")
            logger.error(f"❌ Body: {response.text[:1000]}")
            return {
                "success": False,
                "data": None,
                "detail": "Auth-Token inválido o expirado",
                "raw": response.text,
            }

        # ============================================================
        # 400 / 403: LOGGING MEJORADO (CLAVE PARA DEBUGGING)
        # ============================================================
        if response.status_code in (400, 403):
            body = response.text
            
            logger.error("=" * 60)
            logger.error(f"❌ REQUEST RECHAZADO POR NUVEI ({response.status_code})")
            logger.error(f"❌ Body completo: {body[:1000]}")
            logger.error("=" * 60)
            
            # Intentar parsear JSON para detalle
            try:
                json_body = response.json()
                logger.error(f"📋 JSON parseado: {json_body}")
                
                # Buscar campo de error específico
                if "error" in json_body:
                    logger.error(f"🔍 Campo 'error': {json_body['error']}")
                if "detail" in json_body:
                    logger.error(f"🔍 Campo 'detail': {json_body['detail']}")
                if "message" in json_body:
                    logger.error(f"🔍 Campo 'message': {json_body['message']}")
                    
            except Exception as e:
                logger.error(f"❌ No se pudo parsear JSON: {e}")
            
            logger.error("=" * 60)
            
            return {
                "success": False,
                "data": None,
                "detail": f"Solicitud rechazada por Nuvei ({response.status_code})",
                "raw": body,
            }

        # ============================================================
        # PARSEO DE JSON
        # ============================================================

        data = self._safe_json(response)
        
        if not data:
            logger.error("❌ Respuesta Nuvei no es JSON válido")
            logger.error(f"❌ Raw response: {response.text[:1000]}")
            return {
                "success": False,
                "data": None,
                "detail": "Respuesta Nuvei inválida (no JSON)",
                "raw": response.text,
            }

        # Verificar campo "success" en la respuesta
        if "success" not in data:
            logger.error("❌ Respuesta sin campo 'success'")
            logger.error(f"❌ Data recibida: {data}")
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
            
            # 📋 LOGGING DETALLADO PARA DEBUG
            logger.info("=" * 60)
            logger.info("📊 RESPUESTA COMPLETA DE NUVEI:")
            logger.info(f"📦 Estructura completa: {data}")
            
            # Log específico de campos
            import json
            logger.info(f"📋 JSON formateado:\n{json.dumps(data, indent=2)}")
            
            # Verificar estructura
            if "order" in data:
                logger.info(f"📦 Campo 'order' encontrado: {data['order']}")
                if isinstance(data["order"], dict):
                    logger.info(f"🆔 Order ID: {data['order'].get('id', 'NO_ID')}")
                else:
                    logger.warning(f"⚠️  Campo 'order' no es dict: {type(data['order'])}")
            else:
                logger.warning("⚠️  Campo 'order' NO encontrado en respuesta")
                
            if "payment" in data:
                logger.info(f"💳 Campo 'payment' encontrado: {data['payment']}")
                if isinstance(data["payment"], dict):
                    logger.info(f"🔗 Payment URL: {data['payment'].get('payment_url', 'NO_URL')}")
                else:
                    logger.warning(f"⚠️  Campo 'payment' no es dict: {type(data['payment'])}")
            else:
                logger.warning("⚠️  Campo 'payment' NO encontrado en respuesta")
                
            logger.info("=" * 60)
            
            return {
                "success": True,
                "data": data.get("data", {}), 
                "detail": None,
                "raw": None,
            }

        # ============================================================
        # RESPUESTA CON ERROR REPORTADO POR NUVEI
        # ============================================================

        error_detail = data.get("detail") or data.get("error", {}).get("type") or "Error reportado por Nuvei"
        logger.error(f"❌ Nuvei reportó error: {error_detail}")
        logger.error(f"❌ Data completa: {data}")
        
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



