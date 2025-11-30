from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os

from payments_core import (
    create_payment_intent,
    get_payment_intent,
    update_payment_intent
)
from nuvei_client import NuveiClient

router = APIRouter()

NUVEI_APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
NUVEI_APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
NUVEI_ENV = os.getenv("NUVEI_ENV", "stg")

nuvei = NuveiClient(
    app_code=NUVEI_APP_CODE,
    app_key=NUVEI_APP_KEY,
    environment=NUVEI_ENV
)

class CreatePaymentRequest(BaseModel):
    telegram_id: str
    amount: float


@router.post("/create_payment")
def create_payment(req: CreatePaymentRequest):

    intent_id = create_payment_intent(req.telegram_id, req.amount)

    payload = {
        "user": {
            "id": req.telegram_id,
            "email": f"user{req.telegram_id}@pitiupi.com",
            "name": "Usuario",
            "last_name": "Pitiupi"
        },
        "order": {
            "dev_reference": str(intent_id),
            "amount": req.amount,
            "description": "Recarga de fichas Pitiupi",
            "currency": "USD",
            "vat": 0,
            "inc": 0,
            "installments_type": -1
        },
        "configuration": {
            "partial_payment": False,
            "success_url": "https://t.me/pitiupi_bot",
            "failure_url": "https://t.me/pitiupi_bot",
            "pending_url": "https://t.me/pitiupi_bot",
            "review_url": "https://t.me/pitiupi_bot",
            "expiration_time": 3600
        }
    }

    try:
        response = nuvei.create_linktopay(payload)
        payment_url = response["data"]["payment"]["payment_url"]
        order_id = response["data"]["order"]["id"]

        update_payment_intent(intent_id, order_id=order_id)

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check_payment/{intent_id}")
def check_payment(intent_id: int):

    intent = get_payment_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent no encontrado")

    order_id = intent["order_id"]
    if not order_id:
        return {"paid": False}

    result = nuvei.verify_transaction(order_id)

    try:
        status_detail = result["data"]["order"]["status_detail"]
    except:
        return {"paid": False}

    if status_detail == 3:
        update_payment_intent(intent_id, status="paid")
        return {"paid": True}

    return {"paid": False"}
