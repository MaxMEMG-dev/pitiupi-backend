# ============================================================
# payments_api.py — Creación de LinkToPay Nuvei (Ecuador)
# PITIUPI v5.0 Backend + Bot Telegram
# ============================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import logging

from payments_core import (
    create_payment_intent,
    update_payment_intent,
)
from nuvei_client import NuveiClient
from user_db import get_user_data

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================
# CREDENCIALES NUVEI
# ============================================================
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

if not APP_CODE or not APP_KEY:
    logger.error("❌ NUVEI_APP_CODE_SERVER o NUVEI_APP_KEY_SERVER no configurados")


client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)


# ============================================================
# MODELO REQUEST
# ============================================================
class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float


# ============================================================
# ENDPOINT — CREAR LINKTOPAY
# ============================================================
@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    try:
        logger.info(f"🔎 Iniciando pago TelegramID={req.telegram_id} monto={req.amount}")

        # ------------------------------------------------------------
        # 1️⃣ Obtener usuario desde PostgreSQL
        # ------------------------------------------------------------
        user = get_user_data(req.telegram_id)

        if not user:
            logger.error(f"❌ Usuario {req.telegram_id} no existe en PostgreSQL")
            raise HTTPException(404, "Usuario no encontrado")

        # Validar campos esenciales para Nuvei
        REQUIRED_FIELDS = ["email", "phone", "document_number", "first_name", "city", "country"]

        missing = [f for f in REQUIRED_FIELDS if not user.get(f)]
        if missing:
            logger.error(f"❌ Usuario incompleto. Faltan: {missing}")
            raise HTTPException(
                400,
                f"Perfil incompleto. Faltan: {', '.join(missing)}"
            )

        # ------------------------------------------------------------
        # 2️⃣ Crear intent interno (PITIUPI)
        # ------------------------------------------------------------
        intent_id = create_payment_intent(req.telegram_id, req.amount)
        logger.info(f"📝 Intent interno creado: {intent_id}")

        amount = float(req.amount)

        # ------------------------------------------------------------
        # 3️⃣ PREPARAR PAYLOAD NUVEI (Formato oficial 2025)
        # ------------------------------------------------------------
        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": user["email"],
                "name": user["first_name"],
                "last_name": user["last_name"] or user["first_name"],
                "phone_number": user["phone"],
                "fiscal_number": user["document_number"],
                "fiscal_number_type": "id"
            },
            "billing_address": {
                "street": "Sin calle",
                "city": user["city"],
                "zip": "000000",
                "country": "ECU"
            },
            "order": {
                "dev_reference": str(intent_id),
                "description": "Recarga PITIUPI",
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
                "allowed_payment_methods": ["All"],

                # 🔥 REDIRECCIONES TELEGRAM
                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
                "review_url": "https://t.me/pitiupibot?start=payment_review"
            }
        }

        logger.info(f"📤 Enviando payload a Nuvei → {order_data}")

        # ------------------------------------------------------------
        # 4️⃣ Enviar a Nuvei
        # ------------------------------------------------------------
        nuvei_resp = client.create_linktopay(order_data)

        logger.info(f"📥 Respuesta Nuvei: {nuvei_resp}")

        if not nuvei_resp.get("success"):
            detail = nuvei_resp.get("detail") or "Error desconocido en Nuvei"
            logger.error(f"❌ Error Nuvei → {detail}")
            raise HTTPException(500, f"Error Nuvei: {detail}")

        # ------------------------------------------------------------
        # 5️⃣ Leer datos de Nuvei
        # ------------------------------------------------------------
        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error(f"❌ Nuvei devolvió respuesta incompleta: {nuvei_resp}")
            raise HTTPException(500, "Nuvei no entregó order_id o payment_url")

        # ------------------------------------------------------------
        # 6️⃣ Guardar order_id del intent
        # ------------------------------------------------------------
        update_payment_intent(intent_id, order_id=order_id)

        logger.info(f"✅ LinkToPay generado → Intent {intent_id} | Order {order_id}")

        return {
            "success": True,
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error en create_payment: {e}", exc_info=True)
        raise HTTPException(500, "Error interno creando pago")
