import httpx
import os

class RunaClient:
    def __init__(self):
        # Usamos Playground por ahora
        self.base_url = "https://api.playground.runa.io/v1"
        self.api_key = os.getenv("RUNA_API_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def create_payout(self, payout_uuid, amount, email):
        payload = {
            "external_id": str(payout_uuid),
            "amount": float(amount),
            "currency": "USD",
            "recipient_email": email
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.base_url}/orders", json=payload, headers=self.headers)
            return response.json()
