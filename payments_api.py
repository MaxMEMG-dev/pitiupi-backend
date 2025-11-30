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

# CREDENCIALES
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg").strip().lower()

logger.info(f"🔧 Configuración Nuvei:")
logger.info(f"   APP_CODE: {APP_CODE}")
logger.info(f"   ENV: {ENV}")

client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)


class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float


@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    """Crea un intent interno y genera LinkToPay de Nuvei."""
    try:
        if not APP_CODE or not APP_KEY:
            raise HTTPException(
                status_code=500,
                detail="Credenciales Nuvei no configuradas"
            )

        logger.info(f"💰 Creando pago para user {req.telegram_id}, amount {req.amount}")

        # Crear intent interno
        intent_id = create_payment_intent(user_id=req.telegram_id, amount=req.amount)
        logger.info(f"📝 Intent creado: {intent_id}")

        # Monto en float
        amount = float(req.amount)

        # =============================
        # PAYLOAD CORRECTO PRODUCCIÓN
        # =============================
        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": f"user{req.telegram_id}@pitiupi.com",
                "name": "User",                         # obligatorio en PROD
                "last_name": str(req.telegram_id),
                "phone": "0999999999"                   # obligatorio formato válido
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
            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],    # PRODUCCIÓN SOLO ACEPTA STRINGS
                "success_url": "https://pitiupi.com/success",
                "failure_url": "https://pitiupi.com/failure",
                "pending_url": "https://pitiupi.com/pending",
                "review_url": "https://pitiupi.com/review"
            }
        }

        logger.info(f"📤 Enviando payload a Nuvei: {order_data}")

        # Llamar a Nuvei
        nuvei_resp = client.create_linktopay(order_data)
        logger.info(f"🔎 Respuesta cruda Nuvei: {nuvei_resp}")

        # PRODUCCIÓN: validar success
        if not nuvei_resp.get("success"):
            detail = nuvei_resp.get("detail") or nuvei_resp.get("message") or "Error desconocido"
            
            # Log más claro
            logger.error(f"❌ Error Nuvei -> {detail}")
            raise HTTPException(status_code=500, detail=f"Error Nuvei: {detail}")

        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error(f"❌ Respuesta incompleta de Nuvei: {nuvei_resp}")
            raise HTTPException(status_code=500, detail="Nuvei no devolvió order_id o payment_url")

        # Guardar order_id
        update_payment_intent(intent_id, order_id=order_id)

        logger.info(f"✅ LinkToPay creado: intent={intent_id}, order={order_id}")

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ ERROR /create_payment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno creando pago")
