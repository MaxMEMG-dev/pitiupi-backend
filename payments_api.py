# ============================================================
# payments_api.py — Orquestador de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.0 — Backend Nuvei (AUTÓNOMO, sin Bot Backend)
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
import os
import logging
import uuid

from nuvei_client import NuveiClient

router = APIRouter(tags=["Payments"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO (Render)
# ============================================================

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

# Validación crítica
if not APP_CODE or not APP_KEY:
    raise RuntimeError("❌ NUVEI_APP_CODE_SERVER y NUVEI_APP_KEY_SERVER son obligatorios")

# ============================================================
# CLIENTE NUVEI
# ============================================================

client = NuveiClient(
    app_code=APP_CODE,
    app_key=APP_KEY,
    environment=ENV,
)

logger.info(f"✅ NuveiClient inicializado | env={ENV}")

# ============================================================
# MODELOS PYDANTIC
# ============================================================

class PaymentCreateRequest(BaseModel):
    telegram_id: int = Field(..., gt=0, description="Telegram ID del usuario")
    amount: float = Field(..., gt=0, le=10000, description="Monto en USD")


class PaymentCreateResponse(BaseModel):
    success: bool
    order_id: str
    payment_url: str


# ============================================================
# ENDPOINT PRINCIPAL: GET /payments/pay
# (usado desde botón de Telegram)
# ============================================================

@router.get("/pay")
async def pay_redirect(
    telegram_id: int = Query(..., description="Telegram ID del usuario"),
    amount: float = Query(..., gt=0, le=10000, description="Monto en USD"),
):
    """
    🔥 Flujo directo de pago (SIN BOT BACKEND)

    1. Recibe telegram_id y amount
    2. Construye payload Nuvei
    3. Llama a LinkToPay
    4. Redirige al checkout
    """
    try:
        logger.info("=" * 60)
        logger.info("💰 Iniciando flujo de pago (redirect)")
        logger.info(f"👤 Telegram ID: {telegram_id}")
        logger.info(f"💵 Monto: ${amount} USD")
        logger.info("=" * 60)

        intent_uuid = str(uuid.uuid4())

        # ========================================================
        # PAYLOAD NUVEI (ECUADOR)
        # ========================================================

        nuvei_payload = {
            "user": {
                "id": str(telegram_id),
                "email": "test@pitiupi.com",
                "name": "PITIUPI",
                "last_name": "USER",
                "phone_number": "0999999999",
                "fiscal_number": "0000000000",
            },
            "billing_address": {
                "street": "Sin calle",
                "city": "Quito",
                "zip": "000000",
                "country": "ECU",
            },
            "order": {
                "dev_reference": intent_uuid,
                "description": "Recarga PITIUPI",
                "amount": float(amount),
                "currency": "USD",
                "vat": 0,
                "taxable_amount": float(amount),
                "tax_percentage": 0,
                "installments_type": 0,
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
            },
        }

        logger.info("📦 Payload Nuvei construido")

        # ========================================================
        # LLAMADA A NUVEI
        # ========================================================

        nuvei_resp = client.create_linktopay(nuvei_payload)

        if not nuvei_resp.get("success"):
            logger.error(f"❌ Error Nuvei: {nuvei_resp.get('detail')}")
            raise HTTPException(
                status_code=502,
                detail=nuvei_resp.get("detail", "Error comunicándose con Nuvei"),
            )

        data = nuvei_resp["data"]
        order_id = data["order"]["id"]
        payment_url = data["payment"]["payment_url"]

        logger.info(f"✅ LinkToPay creado | Order ID: {order_id}")
        logger.info(f"🔗 Payment URL: {payment_url}")
        logger.info("=" * 60)

        return RedirectResponse(url=payment_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error crítico en pay_redirect: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# ============================================================
# ENDPOINT API: POST /payments/create_payment
# (usado desde Postman)
# ============================================================

@router.post("/create_payment", response_model=PaymentCreateResponse)
def create_payment(req: PaymentCreateRequest):
    """
    🔥 Endpoint de prueba / API directa
    Devuelve payment_url en JSON
    """
    try:
        logger.info(f"💰 Creando pago | User: {req.telegram_id} | Amount: ${req.amount}")

        intent_uuid = str(uuid.uuid4())

        nuvei_payload = {
            "user": {
                "id": str(req.telegram_id),
                "email": "test@pitiupi.com",
                "name": "PITIUPI",
                "last_name": "USER",
                "phone_number": "0999999999",
                "fiscal_number": "0000000000",
            },
            "billing_address": {
                "street": "Sin calle",
                "city": "Quito",
                "zip": "000000",
                "country": "ECU",
            },
            "order": {
                "dev_reference": intent_uuid,
                "description": "Recarga PITIUPI",
                "amount": float(req.amount),
                "currency": "USD",
                "vat": 0,
                "taxable_amount": float(req.amount),
                "tax_percentage": 0,
                "installments_type": 0,
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
            },
        }

        nuvei_resp = client.create_linktopay(nuvei_payload)

        if not nuvei_resp.get("success"):
            raise HTTPException(
                status_code=502,
                detail=nuvei_resp.get("detail", "Error Nuvei"),
            )

        data = nuvei_resp["data"]
        order_id = data["order"]["id"]
        payment_url = data["payment"]["payment_url"]

        logger.info(f"✅ Link generado | Order ID: {order_id}")

        return PaymentCreateResponse(
            success=True,
            order_id=order_id,
            payment_url=payment_url,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno")


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "module": "payments_api",
        "version": "6.0",
        "nuvei_env": ENV,
    }

# ============================================================
# END OF FILE
# ============================================================
