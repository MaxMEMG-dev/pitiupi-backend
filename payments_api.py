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

        # 2. Crear cliente Nuvei
        nuvei = NuveiClient(APP_CODE, APP_KEY, ENVIRONMENT)

        # 3. Crear orden
        order = {
            "order": {
                "currency": "USD",
                "amount": float(data.amount),
                "description": f"Recarga {data.amount} - Intent {intent_id}",
                "dev_reference": str(intent_id)
            },
            "user": {
                "id": str(data.user_id)  # Telegram ID
            },
            "configuration": {
                "partial_payment": False
            }
        }

        nuvei_response = nuvei.create_linktopay(order)

        # Validación de respuesta Nuvei
        if "response" not in nuvei_response or "status" not in nuvei_response:
            raise HTTPException(status_code=500, detail="Error en Nuvei (respuesta inválida)")

        if nuvei_response["response"]["status"] != "success":
            raise HTTPException(status_code=500, detail="Nuvei rechazó la creación del pago")

        order_id = nuvei_response["payment"]["order_id"]
        redirect_url = nuvei_response["payment"]["payment_url"]

        # 4. Guardar order_id en DB
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
