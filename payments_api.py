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

# ============================================================
# 🔐 CREDENCIALES
# ============================================================

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg").strip().lower()

logger.info("🔧 Configuración Nuvei cargada:")
logger.info(f"   APP_CODE = {APP_CODE}")
logger.info(f"   ENV      = {ENV}")

client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)


# ============================================================
# 🚀 MODELOS DE REQUEST
# ============================================================

class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float


# ============================================================
# 🔥 CREAR LINKTOPAY
# ============================================================

@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    """Crea un intent interno y genera LinkToPay de Nuvei."""
    try:
        if not APP_CODE or not APP_KEY:
            raise HTTPException(
                status_code=500,
                detail="❌ Credenciales Nuvei no configuradas correctamente."
            )

        logger.info(f"💰 Creando pago Nuvei: user={req.telegram_id}, amount={req.amount}")

        # Crear intent interno
        intent_id = create_payment_intent(user_id=req.telegram_id, amount=req.amount)
        logger.info(f"📝 Intent interno creado: {intent_id}")

        # Normalizar monto
        amount = float(req.amount)

        # ============================================================
        # 🔥 PAYLOAD COMPLETO — OBLIGATORIO EN ECUADOR
        # ============================================================
        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": f"user{req.telegram_id}@pitiupi.com",
                "name": "User",
                "last_name": "Pitiupi",

                # OBLIGATORIO EN ECUADOR
                "fiscal_number_type": "CI",
                "fiscal_number": str(req.telegram_id)
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

            # ⚠️ ECUADOR → OBLIGATORIO
            "billing_address": {
                "city": "Quito",
                "zip": "170515",
                "country": "ECU",
                "street": "Av. Pitiupi",
                "house_number": "123"
            },

            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],

                # REDIRECCIONES A TELEGRAM
                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
                "review_url": "https://t.me/pitiupibot?start=payment_review",
            }
        }

        logger.info("📤 Payload enviado a Nuvei:")
        logger.info(order_data)

        # ============================================================
        # 🔗 LLAMAR A NUVEI
        # ============================================================
        nuvei_resp = client.create_linktopay(order_data)

        logger.info("🔎 Respuesta cruda Nuvei:")
        logger.info(nuvei_resp)

        if not nuvei_resp.get("success"):
            msg = nuvei_resp.get("detail") or nuvei_resp.get("message") or "Error desconocido"
            logger.error(f"❌ Nuvei rechazó la solicitud: {msg}")
            raise HTTPException(status_code=500, detail=f"Error Nuvei: {msg}")

        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error("❌ Nuvei devolvió respuesta incompleta:")
            logger.error(nuvei_resp)
            raise HTTPException(status_code=500, detail="Nuvei no devolvió order_id o payment_url")

        # Guardar order_id en DB
        update_payment_intent(intent_id, order_id=order_id)

        logger.info(f"✅ LinkToPay generado exitosamente: order={order_id}")

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ ERROR /create_payment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno creando el LinkToPay")


# ============================================================
# 🔍 STATUS DE UN PAGO (opcional)
# ============================================================

@router.get("/status/{intent_id}")
def payment_status(intent_id: int):
    intent = get_payment_intent(intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent no encontrado")

    return {
        "intent_id": intent_id,
        "status": intent.status,
        "order_id": intent.order_id
    }
