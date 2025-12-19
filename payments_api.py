# ============================================================
# payments_api.py — Creación de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.0 — Backend Nuvei (delegación a bot backend)
# ============================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import os
import logging
import requests

from nuvei_client import NuveiClient

router = APIRouter(tags=["Payments"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO (Render)
# ============================================================
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

if not APP_CODE or not APP_KEY:
    raise RuntimeError("❌ NUVEI_APP_CODE_SERVER y NUVEI_APP_KEY_SERVER son obligatorios")

if not BOT_BACKEND_URL:
    raise RuntimeError("❌ BOT_BACKEND_URL es obligatorio")

if not INTERNAL_API_KEY:
    raise RuntimeError("❌ INTERNAL_API_KEY es obligatorio")

client = NuveiClient(
    app_code=APP_CODE,
    app_key=APP_KEY,
    environment=ENV,
)

# ============================================================
# HELPERS INTERNOS
# ============================================================

def _internal_headers() -> dict:
    """Headers internos entre servicios (V6)"""
    return {
        "X-Internal-API-Key": INTERNAL_API_KEY,
        "Content-Type": "application/json",
    }

# ============================================================
# MODELOS PYDANTIC
# ============================================================

class PaymentCreateRequest(BaseModel):
    telegram_id: int = Field(..., gt=0, description="Telegram ID del usuario")
    amount: float = Field(..., gt=0, le=10000, description="Monto en USD")


class PaymentCreateResponse(BaseModel):
    success: bool
    intent_uuid: str
    intent_id: int
    order_id: str
    payment_url: str

# ============================================================
# BOT BACKEND CALLS
# ============================================================

def call_bot_backend_create_intent(telegram_id: int, amount: float) -> dict:
    url = f"{BOT_BACKEND_URL}/internal/payments/create_intent"

    payload = {
        "telegram_id": telegram_id,
        "amount": amount,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=15,
        )

        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}

        if resp.status_code in (400, 404):
            return {
                "success": False,
                "error": resp.json().get("detail", "Error del bot backend"),
                "status_code": resp.status_code,
            }

        logger.error(f"❌ Bot backend error {resp.status_code}: {resp.text[:200]}")
        return {"success": False, "error": "Error del bot backend", "status_code": 502}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Timeout al bot backend", "status_code": 504}

    except Exception as e:
        logger.error(f"❌ Error llamando al bot backend: {e}", exc_info=True)
        return {"success": False, "error": "Error interno", "status_code": 500}


def call_bot_backend_update_intent(intent_uuid: str, order_id: str, payment_url: str) -> None:
    url = f"{BOT_BACKEND_URL}/internal/payments/update_intent"

    payload = {
        "intent_uuid": intent_uuid,
        "order_id": order_id,
        "payment_url": payment_url,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=10,
        )

        if resp.status_code != 200:
            logger.warning(
                f"⚠️ No se pudo actualizar intent {intent_uuid} | status={resp.status_code}"
            )

    except Exception as e:
        logger.error(f"❌ Error actualizando intent en bot backend: {e}", exc_info=True)

# ============================================================
# POST /payments/create_payment
# ============================================================

@router.post("/create_payment", response_model=PaymentCreateResponse)
def create_payment(req: PaymentCreateRequest):
    """
    Backend Nuvei (V6):
    - Orquesta BOT + Nuvei
    - NO toca DB
    - NO toca balances
    """
    try:
        logger.info(
            f"💰 Create payment | telegram_id={req.telegram_id} | amount=${req.amount:.2f}"
        )

        # 1️⃣ Crear PaymentIntent en BOT
        intent_result = call_bot_backend_create_intent(req.telegram_id, req.amount)

        if not intent_result["success"]:
            raise HTTPException(
                status_code=intent_result.get("status_code", 500),
                detail=intent_result.get("error", "Error creando intent"),
            )

        intent_data = intent_result["data"]
        intent_uuid = intent_data["intent_uuid"]
        intent_id = intent_data["intent_id"]
        user_data = intent_data["user"]

        # 2️⃣ Construir payload Nuvei
        nuvei_payload = {
            "user": {
                "id": str(req.telegram_id),
                "email": user_data["email"],
                "name": user_data["first_name"],
                "last_name": user_data.get("last_name") or user_data["first_name"],
                "phone_number": user_data["phone"],
                "fiscal_number": user_data["document_number"],
            },
            "billing_address": {
                "street": "Sin calle",
                "city": user_data["city"],
                "zip": "000000",
                "country": "ECU",
            },
            "order": {
                "dev_reference": intent_uuid,  # UUID V6
                "description": "Recarga PITIUPI",
                "amount": float(req.amount),
                "currency": "USD",
                "vat": 0,
                "taxable_amount": float(req.amount),
                "tax_percentage": 0,
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
            },
        }

        # 3️⃣ Llamar a Nuvei
        nuvei_resp = client.create_linktopay(nuvei_payload)

        if not nuvei_resp.get("success"):
            raise HTTPException(
                status_code=502,
                detail=nuvei_resp.get("detail", "Error Nuvei"),
            )

        data = nuvei_resp["data"]
        order_id = data["order"]["id"]
        payment_url = data["payment"]["payment_url"]

        # 4️⃣ Guardar datos Nuvei en BOT
        call_bot_backend_update_intent(intent_uuid, order_id, payment_url)

        return PaymentCreateResponse(
            success=True,
            intent_uuid=intent_uuid,
            intent_id=intent_id,
            order_id=order_id,
            payment_url=payment_url,
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
