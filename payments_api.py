from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from nuvei_client import NuveiClient
from payments_core import create_payment_intent, mark_intent_paid, get_payment_intent, update_payment_intent
from database import get_connection
import os

router = APIRouter()

# Credenciales del entorno
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENVIRONMENT = os.getenv("NUVEI_ENV", "stg")  # stg o prod


class PaymentRequest(BaseModel):
    user_id: int
    amount: float


@router.post("/create_payment")
def create_payment(data: PaymentRequest):
    """
    Crea un intent interno + genera un LinkToPay en Nuvei.
    """
    try:
        # 1. Crear intent interno
        intent_id = create_payment_intent(data.user_id, data.amount)

        # 2. Cliente Nuvei
        nuvei = NuveiClient(APP_CODE, APP_KEY, ENVIRONMENT)

        # 3. Crear orden para Nuvei
        order = {
            "order": {
                "currency": "USD",
                "amount": float(data.amount),
                "description": f"Recarga {data.amount} - Intent {intent_id}",
                "dev_reference": str(intent_id)
            },
            "user": {
                "id": str(data.user_id)
            },
            "configuration": {
                "partial_payment": False
            }
        }

        # 4. Llamar a Nuvei
        nuvei_response = nuvei.create_linktopay(order)

        # 5. Validación REAL de Nuvei
        if not nuvei_response.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=f"Nuvei rechazó la creación del pago: {nuvei_response}"
            )

        data_block = nuvei_response["data"]

        order_id = data_block["order"]["id"]
        redirect_url = data_block["payment"]["payment_url"]

        # 6. Guardar order_id en DB
        update_payment_intent(intent_id, order_id=order_id)

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "redirect_url": redirect_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creando pago: {e}")


@router.get("/payment_status/{intent_id}")
def payment_status(intent_id: int):
    """
    Retorna el estado actual del pago en nuestra base interna.
    """
    row = get_payment_intent(intent_id)
    if not row:
        raise HTTPException(status_code=404, detail="Intent no encontrado")

    return row
