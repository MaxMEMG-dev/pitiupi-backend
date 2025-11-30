import base64
import hashlib
import time
import requests
import logging
from typing import Dict, Any
import os

logger = logging.getLogger(__name__)

class NuveiClient:
    def __init__(self, app_code: str, app_key: str, environment: str = "stg"):
        # Validar credenciales de forma más robusta
        self.app_code = app_code or os.getenv("NUVEI_APP_CODE_SERVER")
        self.app_key = app_key or os.getenv("NUVEI_APP_KEY_SERVER")
        self.environment = environment or os.getenv("NUVEI_ENV", "stg")
        
        # Si aún son None, usar valores por defecto (fallback)
        if not self.app_code:
            logger.error("❌ NUVEI_APP_CODE_SERVER no configurada")
            self.app_code = "CREDENCIAL_NO_CONFIGURADA"
            
        if not self.app_key:
            logger.error("❌ NUVEI_APP_KEY_SERVER no configurada") 
            self.app_key = "CREDENCIAL_NO_CONFIGURADA"

        if self.environment == "stg":
            self.base_url = "https://noccapi-stg.paymentez.com"
        else:
            self.base_url = "https://noccapi.paymentez.com"

        logger.info(f"🔧 NuveiClient inicializado en {self.environment}")
        logger.info(f"📝 App Code: {self.app_code[:8]}...")
        logger.info(f"🔑 App Key: {self.app_key[:8]}...")

    def generate_auth_token(self) -> str:
        try:
            timestamp = str(int(time.time()))
            uniq_str = self.app_key + timestamp
            uniq_hash = hashlib.sha256(uniq_str.encode()).hexdigest()
            raw = f"{self.app_code};{timestamp};{uniq_hash}"
            return base64.b64encode(raw.encode()).decode()
        except Exception as e:
            logger.error(f"❌ Error generando auth token: {e}")
            raise

    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/linktopay/init_order/"

        try:
            auth_token = self.generate_auth_token()
        except Exception as e:
            logger.error(f"❌ Error con credenciales Nuvei: {e}")
            return {
                "status": "error",
                "message": "Credenciales Nuvei inválidas o no configuradas"
            }

        headers = {
            "Content-Type": "application/json",
            "Auth-Token": auth_token,
        }

        try:
            logger.info(f"🔗 Creando LinkToPay...")
            logger.info(f"📤 URL: {url}")
            logger.info(f"📦 Order data: {order_data}")
            
            response = requests.post(url, json=order_data, headers=headers, timeout=30)
            logger.info(f"📥 Status Code: {response.status_code}")
            
            result = response.json()
            logger.info(f"📄 Respuesta Nuvei: {result}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error HTTP: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"📄 Respuesta error: {e.response.text}")
            return {
                "status": "error", 
                "message": f"Error de conexión: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ Error inesperado: {e}")
            return {
                "status": "error",
                "message": f"Error inesperado: {str(e)}"
            }

    def verify_transaction(self, order_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/linktopay/check_order/"

        try:
            auth_token = self.generate_auth_token()
        except Exception as e:
            logger.error(f"❌ Error con credenciales Nuvei: {e}")
            return {"status": "error", "message": "Credenciales inválidas"}

        headers = {
            "Content-Type": "application/json", 
            "Auth-Token": auth_token,
        }

        body = {"order_id": order_id}

        try:
            logger.info(f"🔍 Verificando order: {order_id}")
            response = requests.post(url, json=body, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"❌ Error verificando: {e}")
            return {"status": "error", "message": str(e)}
