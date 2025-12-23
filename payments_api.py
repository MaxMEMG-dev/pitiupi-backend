# ============================================================
# payments_api.py — Orquestador de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.0 — Backend Nuvei (sin DB, delegación a Bot)
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
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

# Validación crítica al inicio
if not APP_CODE or not APP_KEY:
    raise RuntimeError("❌ NUVEI_APP_CODE_SERVER y NUVEI_APP_KEY_SERVER son obligatorios")

if not BOT_BACKEND_URL:
    raise RuntimeError("❌ BOT_BACKEND_URL es obligatorio")

if not INTERNAL_API_KEY:
    raise RuntimeError("❌ INTERNAL_API_KEY es obligatorio")

# Inicializar cliente Nuvei
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
    intent_uuid: str
    intent_id: int
    order_id: str
    payment_url: str

# ============================================================
# HELPERS INTERNOS - COMUNICACIÓN CON BOT
# ============================================================

def _internal_headers() -> dict:
    """Headers de autenticación interna entre servicios"""
    return {
        "X-Internal-API-Key": INTERNAL_API_KEY,
        "Content-Type": "application/json",
    }


def call_bot_backend_create_intent(telegram_id: int, amount: float) -> dict:
    """
    Llama al Bot Backend para crear un PaymentIntent
    
    Returns:
        dict: {"success": bool, "data": dict | None, "error": str | None}
    """
    url = f"{BOT_BACKEND_URL}/internal/payments/create_intent"
    payload = {"telegram_id": telegram_id, "amount": amount}

    logger.info(f"📞 Llamando a Bot Backend: create_intent")
    logger.debug(f"📦 Payload: telegram_id={telegram_id}, amount={amount}")

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=15,
        )

        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"✅ Intent creado | UUID: {data.get('intent_uuid')}")
            return {"success": True, "data": data, "error": None}

        logger.error(f"❌ Error Bot Backend {resp.status_code}: {resp.text[:200]}")
        return {
            "success": False,
            "data": None,
            "error": resp.text,
            "status_code": resp.status_code,
        }

    except requests.exceptions.Timeout:
        logger.error("❌ Timeout llamando al Bot Backend (15s)")
        return {"success": False, "data": None, "error": "Timeout Bot Backend"}

    except Exception as e:
        logger.error(f"❌ Error inesperado llamando Bot: {e}", exc_info=True)
        return {"success": False, "data": None, "error": str(e)}


def call_bot_backend_update_intent(intent_uuid: str, order_id: str, payment_url: str) -> None:
    """
    Notifica al Bot Backend con los datos de Nuvei (order_id, payment_url)
    
    Esta llamada es best-effort (si falla, solo se loggea)
    """
    url = f"{BOT_BACKEND_URL}/internal/payments/update_intent"
    payload = {
        "intent_uuid": intent_uuid,
        "order_id": order_id,
        "payment_url": payment_url,
    }

    logger.info(f"📞 Actualizando intent en Bot | UUID: {intent_uuid}")

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=10,
        )

        if resp.status_code == 200:
            logger.info("✅ Intent actualizado en Bot")
        else:
            logger.warning(f"⚠️ Error actualizando intent: {resp.status_code}")

    except Exception as e:
        logger.error(f"❌ Error actualizando intent: {e}")

# ============================================================
# ENDPOINT PRINCIPAL: GET /payments/pay
# ============================================================

@router.get("/pay")
async def pay_redirect(
    telegram_id: int = Query(..., description="Telegram ID del usuario"),
    amount: float = Query(..., gt=0, le=10000, description="Monto en USD"),
):
    """
    🔥 Endpoint usado por el Bot de Telegram
    
    Flujo:
    1. Recibe telegram_id y amount desde el botón de Telegram
    2. Crea PaymentIntent en Bot Backend
    3. Obtiene datos del usuario (email, nombre, documento, etc.)
    4. Construye payload Nuvei con requerimientos Ecuador
    5. Llama a Nuvei LinkToPay
    6. Redirige al usuario a la URL de pago
    
    Returns:
        RedirectResponse: Redirección directa a Nuvei
    """
    try:
        logger.info("=" * 60)
        logger.info(f"💰 Iniciando flujo de pago")
        logger.info(f"👤 Telegram ID: {telegram_id}")
        logger.info(f"💵 Monto: ${amount} USD")
        logger.info("=" * 60)

        # ============================================================
        # 1️⃣ CREAR PAYMENT INTENT EN BOT
        # ============================================================

        intent_result = call_bot_backend_create_intent(telegram_id, amount)

        if not intent_result["success"]:
            logger.error("❌ No se pudo crear el intent en Bot")
            raise HTTPException(
                status_code=intent_result.get("status_code", 500),
                detail=intent_result.get("error", "Error creando intent"),
            )

        intent_data = intent_result["data"]
        intent_uuid = intent_data["intent_uuid"]
        intent_id = intent_data["intent_id"]
        user_data = intent_data["user"]

        logger.info(f"✅ Intent creado | ID: {intent_id} | UUID: {intent_uuid}")

        # ============================================================
        # 2️⃣ CONSTRUIR PAYLOAD NUVEI (ECUADOR)
        # ============================================================

        nuvei_payload = {
            "user": {
                "id": str(telegram_id),
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
                "dev_reference": intent_uuid,  # 🔥 Crucial: UUID del intent
                "description": "Recarga PITIUPI",
                "amount": float(amount),
                "currency": "USD",
                "vat": 0,
                "taxable_amount": float(amount),  # 🇪🇨 Ecuador requirement
                "tax_percentage": 0,              # 🇪🇨 Ecuador requirement
                "installments_type": 0,           # 🇪🇨 Ecuador requirement
            },
            "configuration": {
                "expiration_time": 900,  # 15 minutos
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot?start=payment_success",
                "failure_url": "https://t.me/pitiupibot?start=payment_failed",
                "pending_url": "https://t.me/pitiupibot?start=payment_pending",
            },
        }

        logger.info("📦 Payload Nuvei construido (Ecuador)")

        # ============================================================
        # 3️⃣ LLAMAR A NUVEI LINKTOPAY
        # ============================================================

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

        # ============================================================
        # 4️⃣ ACTUALIZAR INTENT CON DATOS DE NUVEI
        # ============================================================

        call_bot_backend_update_intent(intent_uuid, order_id, payment_url)

        # ============================================================
        # 5️⃣ REDIRIGIR AL USUARIO A NUVEI
        # ============================================================

        logger.info("🚀 Redirigiendo usuario a Nuvei")
        logger.info("=" * 60)

        return RedirectResponse(url=payment_url)

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error crítico en pay_redirect: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error interno del servidor",
        )

# ============================================================
# ENDPOINT ALTERNATIVO: POST /payments/create_payment
# ============================================================

@router.post("/create_payment", response_model=PaymentCreateResponse)
def create_payment(req: PaymentCreateRequest):
    """
    Endpoint POST alternativo para crear pago
    (usado si se necesita desde API en lugar de redirect)
    
    Returns:
        PaymentCreateResponse: Datos del pago creado (sin redirect)
    """
    try:
        logger.info(f"💰 Creando pago | User: {req.telegram_id} | Amount: ${req.amount}")

        # 1️⃣ Crear PaymentIntent
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

        # 4️⃣ Actualizar intent
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
        raise HTTPException(status_code=500, detail="Error interno")

# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check():
    """Health check del módulo payments"""
    return {
        "status": "healthy",
        "module": "payments_api",
        "version": "6.0",
        "nuvei_env": ENV,
        "bot_backend_configured": bool(BOT_BACKEND_URL),
    }

# ============================================================
# END OF FILE
# ============================================================
