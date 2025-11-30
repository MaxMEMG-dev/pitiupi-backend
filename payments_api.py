from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from payments_core import (
    create_payment_intent,
    update_payment_intent,
    get_payment_intent
)
from nuvei_client import NuveiClient
import os

router = APIRouter()

# Credenciales desde variables de entorno
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)

class PaymentCreateRequest(BaseModel):
    user_id: int
    amount: float


@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    """Crea un intent interno y genera LinkToPay de Nuvei."""
    try:
        # Crear intent interno
        intent_id = create_payment_intent(
            user_id=req.user_id,
            amount=req.amount
        )

        # Generar orden LinkToPay
        order_data = {
            "user": {
                "id": str(req.user_id),
                "email": f"user{req.user_id}@pitiupi.com",
                "name": f"Pitiupi User {req.user_id}",
                "last_name": "Bot"
            },
            "order": {
                "dev_reference": str(intent_id),
                "description": "Recarga Pitiupi",
                "amount": req.amount,
                "currency": "USD",
                "installments_type": -1,
                "vat": 0
            },
            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://pitiupi.com/success",
                "failure_url": "https://pitiupi.com/failure",
                "pending_url": "https://pitiupi.com/pending",
                "review_url": "https://pitiupi.com/review"
            }
        }

        nuvei_resp = client.create_linktopay(order_data)

        # Obtener el order_id real de Nuvei
        order_id = nuvei_resp.get("data", {}).get("order", {}).get("id")
        payment_url = nuvei_resp.get("data", {}).get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            raise HTTPException(status_code=500, detail="Error creando pago en Nuvei")

        # Guardar order_id en DB
        update_payment_intent(intent_id, order_id=order_id)

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except Exception as e:
        print("ERROR /create_payment:", str(e))
        raise HTTPException(status_code=500, detail="Error creando pago")


@router.get("/check_payment/{intent_id}")
def check_payment(intent_id: int):
    """Consulta Nuvei para validar si el pago fue aprobado."""
    intent = get_payment_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent no encontrado")

    order_id = intent["order_id"]
    if not order_id:
        raise HTTPException(status_code=400, detail="Orden sin order_id asignado")

    # Consulta en Nuvei
    nuvei_status = client.verify_transaction(order_id)

    status = nuvei_status.get("transaction", {}).get("status")
    detail = nuvei_status.get("transaction", {}).get("status_detail")
    tx_id = nuvei_status.get("transaction", {}).get("id")
    auth_code = nuvei_status.get("transaction", {}).get("authorization_code")

    if status == "success" and detail == 3:
        from payments_core import mark_intent_paid
        mark_intent_paid(intent_id, tx_id, detail, auth_code)
        return {"status": "paid", "tx_id": tx_id}

    return {"status": "pending"}
