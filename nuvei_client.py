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
        # VALIDAR CREDENCIALES
        if not app_code or not app_key:
            logger.error("❌ CREDENCIALES FALTANTES: app_code o app_key son None")
            raise ValueError("Credenciales Nuvei no configuradas")
            
        self.app_code = app_code
        self.app_key = app_key
        self.environment = environment

        if environment == "stg":
            self.base_url = "https://noccapi-stg.paymentez.com"
        else:
            self.base_url = "https://noccapi.paymentez.com"

        logger.info(f"✅ NuveiClient inicializado: {self.app_code[:10]}... en {environment}")

    def generate_auth_token(self) -> str:
        timestamp = str(int(time.time()))
        uniq_str = self.app_key + timestamp
        uniq_hash = hashlib.sha256(uniq_str.encode()).hexdigest()
        raw = f"{self.app_code};{timestamp};{uniq_hash}"
        return base64.b64encode(raw.encode()).decode()

    def create_linktopay(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/linktopay/init_order/"

        headers = {
            "Content-Type": "application/json",
            "Auth-Token": self.generate_auth_token(),
        }

        try:
            logger.info(f"🔗 Creando LinkToPay en Nuvei {self.environment}...")
            logger.info(f"📤 Enviando a {url}")
            
            response = requests.post(url, json=order_data, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"📥 Respuesta Nuvei: {result}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error HTTP creando LinkToPay: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"📄 Respuesta error: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"❌ Error inesperado creando LinkToPay: {e}")
            raise

    def verify_transaction(self, order_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/linktopay/check_order/"

        headers = {
            "Content-Type": "application/json",
            "Auth-Token": self.generate_auth_token(),
        }

        body = {"order_id": order_id}

        try:
            logger.info(f"🔍 Verificando transacción para order {order_id}")
            response = requests.post(url, json=body, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"❌ Error verificando transacción {order_id}: {e}")
            raise
