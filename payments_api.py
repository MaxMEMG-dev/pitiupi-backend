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

router = APIRouter()
logger = logging.getLogger(__name__)

# Credenciales desde variables de entorno
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)


class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float


@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    """Crea un intent interno y genera LinkToPay de Nuvei."""
    try:
        logger.info(f"Creando pago para user {req.telegram_id}, amount {req.amount}")

        # 1) Crear intent interno sin order_id
        intent_id = create_payment_intent(
            user_id=req.telegram_id,
            amount=req.amount
        )

        logger.info(f"Intent creado: {intent_id}")

        # 2) Preparar datos para Nuvei (amount debe ser string con 2 decimales)
        amount_str = f"{req.amount:.2f}"

        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": f"user{req.telegram_id}@pitiupi.com",
                "first_name": f"User",
                "last_name": f"{req.telegram_id}",
                "phone": "123456789"
            },
            "order": {
                "dev_reference": str(intent_id),
                "description": "Recarga Pitiupi",
                "amount": amount_str,  # ¡IMPORTANTE: string, no float!
                "currency": "USD",
                "installments_type": 0,  # Cambiado de -1 a 0
            },
            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],  # Métodos específicos
                "success_url": "https://pitiupi.com/success",
                "failure_url": "https://pitiupi.com/failure",
                "pending_url": "https://pitiupi.com/pending",
                "review_url": "https://pitiupi.com/review"
            }
        }

        logger.info(f"Enviando a Nuvei: {order_data}")
        nuvei_resp = client.create_linktopay(order_data)
        logger.info(f"Respuesta Nuvei: {nuvei_resp}")

        # 3) Validar respuesta de Nuvei
        if nuvei_resp.get("status") != "success":
            error_msg = nuvei_resp.get("message", "Error desconocido de Nuvei")
            logger.error(f"Nuvei error: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Error Nuvei: {error_msg}")

        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error(f"Respuesta incompleta de Nuvei: {nuvei_resp}")
            raise HTTPException(status_code=500, detail="Nuvei no devolvió order_id o payment_url")

        # 4) Guardar order_id en DB
        update_payment_intent(intent_id, order_id=order_id)

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ERROR /create_payment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno creando pago")


@router.get("/check_payment/{intent_id}")
def check_payment(intent_id: int):
    """Consulta Nuvei para validar si el pago fue aprobado."""
    try:
        intent = get_payment_intent(intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent no encontrado")

        order_id = intent["order_id"]
        if not order_id:
            raise HTTPException(status_code=400, detail="Intent sin order_id asignado")

        # 1) Consultar en Nuvei
        nuvei_status = client.verify_transaction(order_id)
        logger.info(f"Status Nuvei para order {order_id}: {nuvei_status}")

        transaction = nuvei_status.get("transaction", {})
        status = transaction.get("status")
        detail = transaction.get("status_detail")
        tx_id = transaction.get("id")
        auth_code = transaction.get("authorization_code")

        if status == "success" and detail == 3:
            from payments_core import mark_intent_paid
            mark_intent_paid(intent_id, tx_id, detail, auth_code)
            return {"paid": True}

        return {"paid": False}
    
    except Exception as e:
        logger.error(f"ERROR /check_payment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error verificando pago")
