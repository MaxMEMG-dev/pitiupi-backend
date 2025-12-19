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
    
    Note:
        - Stateless (no mantiene sesión)
        - Thread-safe (sin estado mutable)
        - Retorna datos crudos normalizados
        - El Service Layer decide qué hacer con la respuesta
    """

    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        """
        Inicializa cliente Nuvei
        
        Args:
            app_code: Código de aplicación Nuvei
            app_key: Clave secreta del servidor
            environment: "prod" o "stg" (staging)
        
        Note:
            - Configuración debe venir de variables de entorno
            - No hardcodear credenciales
        """
        self.app_code = app_code
        self.app_key = app_key

        if environment == "prod":
            self.base_url = "https://noccapi.paymentez.com"
        else:
            self.base_url = "https://noccapi-stg.paymentez.com"

        logger.info(f"🌐 NuveiClient inicializado | Environment={environment}")
        logger.info(f"🔑 Base URL: {self.base_url}")

    # ============================================================
    # AUTENTICACIÓN
    # ============================================================

    def generate_auth_token(self) -> str:
        """
        V6: Genera Auth-Token según especificación oficial Nuvei
        
        Formula:
        1. uniq_string = app_key + timestamp
        2. uniq_hash = SHA256(uniq_string)
        3. raw = "app_code;timestamp;uniq_hash"
        4. token = Base64(raw)
        
        Returns:
            Token de autenticación Base64
        
        Note:
            - Timestamp en segundos (Unix epoch)
            - SHA256 en hexadecimal lowercase
            - Token válido por tiempo limitado
        """
        timestamp = str(int(time.time()))

        # Hash: SHA256(app_key + timestamp)
        uniq_string = self.app_key + timestamp
        uniq_hash = hashlib.sha256(uniq_string.encode()).hexdigest()

        # Format: app_code;timestamp;hash
        raw = f"{self.app_code};{timestamp};{uniq_hash}"
        
        # Base64 encode
        token = base64.b64encode(raw.encode()).decode()

        logger.debug(f"🔐 Auth-Token generado | Timestamp={timestamp}")
        return token

    # ============================================================
    # CREAR LINKTOPAY
    # ============================================================

    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        V6: Crea orden LinkToPay en Nuvei
        
        Args:
            order_data: Diccionario con estructura de orden Nuvei
                Required keys:
                - user: {id, email, name, ...}
                - billing_address: {street, city, country, ...}
                - order: {dev_reference, amount, currency, ...}
                - configuration: {expiration_time, success_url, ...}
        
        Returns:
            Dict normalizado V6:
            {
                "success": bool,
                "data": dict | None,  # Solo si success=True
                "detail": str | None,  # Mensaje de error
                "raw": str | None,  # Respuesta cruda (debug)
            }
        
        Note:
            - Timeout de 15 segundos (fail-fast)
            - Manejo robusto de errores HTTP
            - No asume éxito financiero
            - El Service Layer decide qué hacer con la respuesta
        """
        url = f"{self.base_url}/linktopay/init_order/"

        headers = {
            "Content-Type": "application/json",
            "Auth-Token": self.generate_auth_token()
        }

        # Log seguro (ocultar Auth-Token en producción)
        safe_headers = headers.copy()
        safe_headers["Auth-Token"] = "***REDACTED***"
        
        logger.info(f"➡ POST {url}")
        logger.debug(f"➡ Headers: {safe_headers}")
        logger.debug(f"➡ Payload: {order_data}")

        # ============================================================
        # REQUEST HTTP CON TIMEOUT
        # ============================================================
        try:
            response = requests.post(
                url,
                json=order_data,
                headers=headers,
                timeout=5  # 5 segundos (fail-fast)
            )

        except requests.exceptions.Timeout:
            logger.error("❌ Timeout conectando a Nuvei (15s)")
            return {
                "success": False,
                "data": None,
                "detail": "Timeout al conectar con Nuvei (15 segundos)",
                "raw": None,
            }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Error de conexión con Nuvei: {e}")
            return {
                "success": False,
                "data": None,
                "detail": f"Error de conexión con Nuvei: {str(e)}",
                "raw": None,
            }

        except Exception as e:
            logger.error(f"❌ Error inesperado llamando a Nuvei: {e}", exc_info=True)
            return {
                "success": False,
                "data": None,
                "detail": f"Error inesperado: {str(e)}",
                "raw": None,
            }

        # ============================================================
        # MANEJO DE STATUS CODES HTTP
        # ============================================================
        
        # 500+ (Error del servidor Nuvei)
        if response.status_code >= 500:
            logger.error(f"❌ Nuvei error 500+: {response.status_code} | {response.text[:200]}")
            return {
                "success": False,
                "data": None,
                "detail": f"Error interno de Nuvei ({response.status_code})",
                "raw": response.text,
            }

        # 401 (Auth-Token inválido)
        if response.status_code == 401:
            logger.error("❌ Auth-Token inválido (401)")
            return {
                "success": False,
                "data": None,
                "detail": "Auth-Token inválido (401). Verificar credenciales.",
                "raw": response.text,
            }

        # 400 (Payload inválido)
        if response.status_code == 400:
            logger.error(f"❌ Payload inválido (400): {response.text[:200]}")
            parsed = self._safe_json(response)
            return {
                "success": False,
                "data": None,
                "detail": "Payload inválido (400). Revisar estructura de orden.",
                "raw": response.text,
            }

        # 403 (Forbidden - permisos)
        if response.status_code == 403:
            logger.error(f"❌ Forbidden (403): {response.text[:200]}")
            return {
                "success": False,
                "data": None,
                "detail": "Acceso denegado (403). Verificar permisos de app_code.",
                "raw": response.text,
            }

        # ============================================================
        # PARSEAR RESPUESTA JSON
        # ============================================================
        data = self._safe_json(response)

        if data is None:
            logger.error(f"❌ Respuesta Nuvei no es JSON válido: {response.text[:200]}")
            return {
                "success": False,
                "data": None,
                "detail": "Nuvei devolvió una respuesta no JSON (posible HTML de error)",
                "raw": response.text,
            }

        logger.info(f"✅ Respuesta Nuvei recibida: status={response.status_code}")
        logger.debug(f"📄 JSON completo: {data}")

        # ============================================================
        # VALIDAR ESTRUCTURA MÍNIMA
        # ============================================================
        if not isinstance(data, dict) or "success" not in data:
            logger.error(f"❌ Respuesta Nuvei inválida, falta campo 'success': {data}")
            return {
                "success": False,
                "data": None,
                "detail": "Respuesta Nuvei inválida (falta campo 'success')",
                "raw": str(data),
            }

        # ============================================================
        # NORMALIZAR RESPUESTA V6
        # ============================================================
        # Nuvei devuelve {"success": bool, ...}
        # Normalizamos a estructura V6
        nuvei_success = data.get("success", False)
        
        if nuvei_success:
            return {
                "success": True,
                "data": data,  # Respuesta completa de Nuvei
                "detail": None,
                "raw": None,
            }
        else:
            # Error reportado por Nuvei (success=false)
            error_detail = data.get("detail") or data.get("error") or "Error desconocido de Nuvei"
            logger.warning(f"⚠️ Nuvei reportó error: {error_detail}")
            
            return {
                "success": False,
                "data": None,
                "detail": error_detail,
                "raw": str(data),
            }

    # ============================================================
    # UTILIDADES PRIVADAS
    # ============================================================

    def _safe_json(self, response) -> Optional[Dict[str, Any]]:
        """
        V6: Parsea JSON de forma segura
        
        Args:
            response: Response object de requests
        
        Returns:
            Dict parseado o None si falla
        
        Note:
            - Captura excepciones de JSON inválido
            - Nuvei a veces retorna HTML en vez de JSON (errores 500)
        """
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            logger.debug("⚠️ Respuesta no es JSON válido")
            return None
        except Exception as e:
            logger.debug(f"⚠️ Error parseando JSON: {e}")
            return None
