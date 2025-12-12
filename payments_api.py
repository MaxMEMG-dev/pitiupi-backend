# ============================================================
# payments_api.py — Creación de LinkToPay Nuvei (Ecuador)
# PITIUPI v5.1 Backend + Bot Telegram (CORREGIDO)
# ============================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
import os
import logging

from payments_core import (
    create_payment_intent,
    update_payment_intent,
    get_payment_intent,
)
from nuvei_client import NuveiClient
from database import get_connection

router = APIRouter(tags=["Payments"])
logger = logging.getLogger(__name__)


# ============================================================
# CREDENCIALES NUVEI (ÚNICA FUENTE DE VERDAD)
# ============================================================

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

if not APP_CODE or not APP_KEY:
    logger.error("❌ NUVEI_APP_CODE_SERVER o NUVEI_APP_KEY_SERVER no configurados")

client = NuveiClient(
    app_code=APP_CODE,
    app_key=APP_KEY,
    environment=ENV,
)


# ============================================================
# FUNCIÓN LOCAL — OBTENER USUARIO DESDE POSTGRESQL
# ============================================================

def get_user_data(telegram_id: int):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                telegram_id,
                telegram_first_name AS first_name,
                telegram_last_name  AS last_name,
                email,
                phone,
                country,
                city,
                document_number
            FROM users
            WHERE telegram_id = %s
            LIMIT 1;
            """,
            (telegram_id,)
        )

        return cursor.fetchone()

    except Exception as e:
        logger.error(
            f"❌ Error obteniendo usuario {telegram_id}: {e}",
            exc_info=True
        )
        return None

    finally:
        if conn:
            conn.close()


# ============================================================
# MODELO REQUEST
# ============================================================

class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float

    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("El monto debe ser mayor a 0")
        return v


# ============================================================
# POST /payments/create_payment
# ============================================================

@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    try:
        logger.info(
            f"🔎 Creando pago | TelegramID={req.telegram_id} | Amount={req.amount}"
        )

        # ----------------------------------------------------
        # 1️⃣ Obtener usuario
        # ----------------------------------------------------
        user = get_user_data(req.telegram_id)
        if not user:
            raise HTTPException(404, "Usuario no encontrado")

        # ----------------------------------------------------
        # 2️⃣ Validar perfil obligatorio
        # ----------------------------------------------------
        required_fields = [
            "email",
            "phone",
            "document_number",
            "first_name",
            "city",
            "country",
        ]

        missing = [f for f in required_fields if not user[f]]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Perfil incompleto. Faltan: {', '.join(missing)}"
            )

        # ----------------------------------------------------
        # 3️⃣ Crear PaymentIntent INTERNO (CRÍTICO)
        # ----------------------------------------------------
        amount = float(req.amount)

        intent_id = create_payment_intent(
            telegram_id=req.telegram_id,
            amount=amount,
            application_code=APP_CODE,  # 🔥 CLAVE PARA STOKEN
        )

        logger.info(f"📝 PaymentIntent creado → ID={intent_id}")

        # ----------------------------------------------------
        # 4️⃣ Payload OFICIAL Nuvei LinkToPay
        # ----------------------------------------------------
        order_data = {
            "user": {
                "id": str(req.telegram_id),   # DEBE SER STRING
                "email": user["email"],
                "name": user["first_name"],
                "last_name": user["last_name"] or user["first_name"],
                "phone_number": user["phone"],
                "fiscal_number": user["document_number"],
            },
            "billing_address": {
                "street": "Sin calle",
                "city": user["city"],
                "zip": "000000",
                "country": "ECU",
            },
            "order": {
                "dev_reference": str(intent_id),  # ← REFERENCIA INTERNA
                "description": "Recarga PITIUPI",
                "amount": amount,
                "currency": "USD",
                "installments_type": 0,
                "vat": 0,
                "taxable_amount": amount,
                "tax_percentage": 0,
            },
            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
                "review_url": "https://t.me/pitiupibot?start=payment_review",
            },
        }

        logger.info("📤 Enviando LinkToPay a Nuvei")

        # ----------------------------------------------------
        # 5️⃣ Enviar a Nuvei
        # ----------------------------------------------------
        nuvei_resp = client.create_linktopay(order_data)

        if not nuvei_resp.get("success"):
            raise HTTPException(
                502,
                f"Error Nuvei: {nuvei_resp.get('detail')}"
            )

        # ----------------------------------------------------
        # 6️⃣ Extraer respuesta
        # ----------------------------------------------------
        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            raise HTTPException(
                500,
                "Nuvei no devolvió order_id o payment_url"
            )

        # ----------------------------------------------------
        # 7️⃣ Guardar order_id
        # ----------------------------------------------------
        update_payment_intent(intent_id, order_id=order_id)

        logger.info(
            f"✅ LinkToPay OK | Intent={intent_id} | Order={order_id}"
        )

        return {
            "success": True,
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"❌ Error creando LinkToPay: {e}",
            exc_info=True
        )
        raise HTTPException(500, "Error interno creando pago")


# ============================================================
# GET /payments/get_intent/{intent_id}
# ============================================================

@router.get("/get_intent/{intent_id}")
def get_intent(intent_id: int):
    intent = get_payment_intent(intent_id)
    if not intent:
        raise HTTPException(404, "Intent no encontrado")

    return {
        "success": True,
        "intent": intent,
    }
