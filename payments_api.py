from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import logging

from payments_core import (
    create_payment_intent,
    update_payment_intent,
    get_payment_intent
)
from nuvei_client import NuveiClient
from users_db import get_user_data  # <-- nueva función para obtener datos reales

router = APIRouter()
logger = logging.getLogger(__name__)

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)


class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float


@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    try:
        user = get_user_data(req.telegram_id)  # ← datos reales desde DB

        if not user:
            raise HTTPException(404, "Usuario no encontrado")

        intent_id = create_payment_intent(user_id=req.telegram_id, amount=req.amount)
        amount = float(req.amount)

        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": user.email,
                "name": user.first_name,
                "last_name": user.last_name or user.first_name,
                "phone_number": user.phone,
                "fiscal_number": user.document_number,
                "fiscal_number_type": "cedula"
            },

            "order": {
                "dev_reference": str(intent_id),
                "description": "Recarga Pitiupi",
                "amount": amount,
                "currency": "USD",
                "installments_type": 0,
                "vat": 0,
                "taxable_amount": amount,
                "tax_percentage": 0
            },

            "billing_address": {
                "street": "Sin calle",
                "city": user.city,
                "state": "",
                "district": "",
                "zip": "000000",
                "country": "ECU"
            },

            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],

                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
                "review_url": "https://t.me/pitiupibot?start=payment_review",
            }
        }

        nuvei_resp = client.create_linktopay(order_data)

        if not nuvei_resp.get("success"):
            raise HTTPException(500, f"Error Nuvei: {nuvei_resp.get('detail')}")

        data = nuvei_resp["data"]
        order_id = data["order"]["id"]
        payment_url = data["payment"]["payment_url"]

        update_payment_intent(intent_id, order_id=order_id)

        return {"intent_id": intent_id, "order_id": order_id, "payment_url": payment_url}

    except Exception as e:
        logger.error(f"Error en create_payment: {e}")
        raise HTTPException(500, "Error interno creando pago")
