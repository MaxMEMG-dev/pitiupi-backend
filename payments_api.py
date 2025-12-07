from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import logging
import sqlite3

from payments_core import (
    create_payment_intent,
    update_payment_intent,
)
from nuvei_client import NuveiClient

router = APIRouter()
logger = logging.getLogger(__name__)

# ============ CREDENCIALES ============
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg").strip().lower()

client = NuveiClient(APP_CODE, APP_KEY, ENV)


DB_PATH = "./pitiupi.db"


class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float


def get_user(telegram_id: int):
    """Obtiene los datos reales del usuario desde SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            telegram_first_name,
            telegram_username,
            email,
            phone,
            country,
            city,
            document_number
        FROM users
        WHERE telegram_id = ?
    """, (str(telegram_id),))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "first_name": row[0],
        "username": row[1],
        "email": row[2],
        "phone": row[3],
        "country": row[4],
        "city": row[5],
        "document": row[6],
    }


@router.post("/create_payment")
def create_payment(req: PaymentCreateRequest):
    """Crea un intent interno y genera LinkToPay de Nuvei."""
    try:
        if not APP_CODE or not APP_KEY:
            raise HTTPException(
                status_code=500,
                detail="Credenciales Nuvei no configuradas"
            )

        # ================================
        # 1. Obtener datos reales del usuario
        # ================================
        user = get_user(req.telegram_id)

        if not user:
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado en la base de datos"
            )

        logger.info(f"🧍 Usuario cargado: {user}")

        # ================================
        # 2. Crear intent interno
        # ================================
        intent_id = create_payment_intent(
            user_id=req.telegram_id,
            amount=req.amount
        )
        logger.info(f"📝 Intent creado: {intent_id}")

        amount = float(req.amount)

        # ================================
        # 3. PAYLOAD COMPLETO PARA NUVÉI (ECUADOR)
        # ================================
        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": user["email"],
                "name": user["first_name"],
                "last_name": user["document"],  # Apellidos no tenemos → colocamos DNI
                "phone_number": user["phone"],
                "fiscal_number_type": "dni",
                "fiscal_number": user["document"]
            },
            "order": {
                "dev_reference": str(intent_id),
                "description": "Recarga de saldo Pitiupi",
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

                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
                "review_url": "https://t.me/pitiupibot?start=payment_review"
            },
            "billing_address": {
                "street": "N/A",
                "city": user["city"],
                "zip": "000000",
                "country": "ECU"
            }
        }

        logger.info(f"📤 Payload enviado a Nuvei: {order_data}")

        # ================================
        # 4. Enviar a Nuvei
        # ================================
        nuvei_resp = client.create_linktopay(order_data)

        if not nuvei_resp.get("success"):
            detail = nuvei_resp.get("detail") or "Error desconocido"
            logger.error(f"❌ Error Nuvei: {detail}")
            raise HTTPException(status_code=500, detail=f"Error Nuvei: {detail}")

        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error("❌ Nuvei no devolvió order_id o payment_url")
            raise HTTPException(status_code=500, detail="Respuesta incompleta de Nuvei")

        update_payment_intent(intent_id, order_id=order_id)

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ ERROR interno en /create_payment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno creando pago")
