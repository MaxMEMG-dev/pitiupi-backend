import httpx
import os
from typing import Dict, Any, Optional

class RunaClient:
    def __init__(self):
        # Configuración según documentación oficial
        # Playground: https://playground.runa.io (Keys empiezan con XX)
        # Production: https://api.runa.io (Keys empiezan con wg)
        
        env_mode = os.getenv("RUNA_ENV", "playground").lower()
        
        if env_mode == "production":
            self.base_url = "https://api.runa.io"
        else:
            self.base_url = "https://playground.runa.io"

        self.api_key = os.getenv("RUNA_API_KEY", "")
        
        # IMPORTANTE: Según la documentación, el header es 'X-Api-Key'
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def check_connection(self) -> bool:
        """
        Verifica si la API Key es válida usando el endpoint /v2/ping
        Documentación: GET https://playground.runa.io/v2/ping
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{self.base_url}/v2/ping", headers=self.headers)
                if response.status_code == 200 and response.json().get("message") == "pong":
                    return True
                return False
            except Exception as e:
                print(f"Error conectando con Runa: {e}")
                return False

    async def create_payout_order(self, 
                                  payout_uuid: str, 
                                  amount: float, 
                                  email: str, 
                                  currency: str = "USD") -> Dict[str, Any]:
        """
        Crea una orden de pago.
        """
        payload = {
            "external_id": str(payout_uuid),
            "amount": amount,
            "currency": currency,
            "recipient_email": email,
            # delivery_method dependerá de lo que Runa habilite en tu cuenta
            # por defecto intentamos enviar un link de pago
            "delivery_method": "payout_link" 
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/orders", # Endpoint estándar de órdenes
                json=payload, 
                headers=self.headers
            )
            return response.json()
