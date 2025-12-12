# ============================================================
# payments_api.py — Creación de LinkToPay Nuvei (Ecuador)
# PITIUPI v5.0 Backend + Bot Telegram
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
# FUNCIÓN LOCAL: Obtener datos de usuario desde PostgreSQL
# ============================================================
def get_user_data(telegram_id: int):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                telegram_id,
                telegram_first_name AS first_name,
                telegram_last_name  AS last_name,
                email,
                phone,
                country,
                city,
                document_number,
                created_at
            FROM users
            WHERE telegram_id = %s
            LIMIT 1;
        """

        cursor.execute(query, [telegram_id])
        row = cursor.fetchone()

        if not row:
            logger.warning(f"⚠️ Usuario {telegram_id} no existe en PostgreSQL")
            return None

        return row

    except Exception as e:
        logger.error(f"❌ Error obteniendo usuario {telegram_id}: {e}", exc_info=True)
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
            raise HTTPException(404, "Usuario no encontrado")

        # ------------------------------------------------------------
        # Validar campos obligatorios sin usar .get()
        # (RealDictRow no soporta .get de forma consistente)
        # ------------------------------------------------------------
        REQUIRED_FIELDS = ["email", "phone", "document_number", "first_name", "city", "country"]

        missing = []
        for field in REQUIRED_FIELDS:
            value = user[field] if field in user else None
            if not value:
                missing.append(field)

        if missing:
            logger.error(f"❌ Usuario incompleto. Faltan: {missing}")
            raise HTTPException(
                400,
                f"Perfil incompleto. Faltan: {', '.join(missing)}"
            )

        # ------------------------------------------------------------
        # 2️⃣ Crear intent interno
        # ------------------------------------------------------------
        amount = float(req.amount)
        intent_id = create_payment_intent(req.telegram_id, amount, application_code=APP_CODE)

        logger.info(f"📝 Intent interno creado: {intent_id}")

        # ------------------------------------------------------------
        # 3️⃣ PREPARAR PAYLOAD OFICIAL NUVEI 2025
        # ------------------------------------------------------------
        order_data = {
            "user": {
                "id": str(req.telegram_id),
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
                "dev_reference": str(intent_id),
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
            raise HTTPException(500, f"Error Nuvei: {detail}")

        # ------------------------------------------------------------
        # 5️⃣ Leer datos obligatorios
        # ------------------------------------------------------------
        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error(f"❌ Respuesta incompleta de Nuvei: {nuvei_resp}")
            raise HTTPException(500, "Nuvei no entregó order_id o payment_url")

        # ------------------------------------------------------------
        # 6️⃣ Guardar order_id del intent interno
        # ------------------------------------------------------------
        update_payment_intent(intent_id, order_id=order_id)

        logger.info(f"✅ LinkToPay generado → Intent {intent_id} | Order {order_id}")

        return {
            "success": True,
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url,
        }

    except HTTPException:
        raise

    except ValueError as e:
        logger.error(f"❌ Error de validación: {e}")
        raise HTTPException(400, str(e))

    except Exception as e:
        logger.error(f"❌ Error en create_payment: {e}", exc_info=True)
        raise HTTPException(500, "Error interno creando pago")


# ============================================================
# ENDPOINT — OBTENER INTENT POR ID
# ============================================================
@router.get("/get_intent/{intent_id}")
def get_intent(intent_id: int):
    intent = get_payment_intent(intent_id)
    if not intent:
        raise HTTPException(404, "Intent no encontrado")
    return {"success": True, "intent": intent}
