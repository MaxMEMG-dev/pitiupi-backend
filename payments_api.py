# ============================================================
# payments_api.py — Orquestador de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.1 — Backend Nuvei (CORREGIDO)
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
import os
import logging
import time

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
    email: str = Field(..., description="Email del usuario")
    name: str = Field(..., description="Nombre del usuario")
    last_name: str = Field(..., description="Apellido del usuario")
    phone_number: str = Field(..., min_length=10, max_length=10, description="Teléfono (10 dígitos)")
    fiscal_number: str = Field(..., min_length=10, max_length=13, description="Cédula o RUC")
    street: str = Field(default="Sin calle", description="Dirección")
    city: str = Field(default="Quito", description="Ciudad")
    zip_code: str = Field(default="170102", description="Código postal")


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
    email: str = Query(..., description="Email del usuario"),
    name: str = Query(..., description="Nombre del usuario"),
    last_name: str = Query(..., description="Apellido del usuario"),
    phone_number: str = Query(..., description="Teléfono (10 dígitos)"),
    fiscal_number: str = Query(..., description="Cédula o RUC"),
    street: str = Query(default="Sin calle", description="Dirección"),
    city: str = Query(default="Quito", description="Ciudad"),
    zip_code: str = Query(default="170102", description="Código postal"),
):
    """
    🔥 Flujo directo de pago (SIN BOT BACKEND)

    1. Recibe datos completos del usuario
    2. Construye payload Nuvei con datos reales
    3. Llama a LinkToPay
    4. Redirige al checkout
    """
    try:
        logger.info("=" * 60)
        logger.info("💰 Iniciando flujo de pago (redirect)")
        logger.info(f"👤 Telegram ID: {telegram_id}")
        logger.info(f"💵 Monto: ${amount} USD")
        logger.info(f"📧 Email: {email}")
        logger.info(f"👤 Usuario: {name} {last_name}")
        logger.info("=" * 60)

        # ========================================================
        # GENERACIÓN DE dev_reference (CORREGIDO)
        # ========================================================
        # ❌ NUNCA usar UUID con guiones
        # ✅ Formato: PITIUPI-{telegram_id}-{timestamp}
        
        dev_reference = f"PITIUPI-{telegram_id}-{int(time.time())}"
        logger.info(f"🔑 dev_reference generado: {dev_reference}")

        # ========================================================
        # PAYLOAD NUVEI (ECUADOR) — CORREGIDO
        # ========================================================

        nuvei_payload = {
            "user": {
                "id": str(telegram_id),  # ✅ CORREGIDO: era req.telegram_id
                "email": email,  # ✅ DATO REAL
                "name": name,  # ✅ DATO REAL
                "last_name": last_name,  # ✅ DATO REAL
                "phone_number": phone_number,  # ✅ DATO REAL
                "fiscal_number": fiscal_number  # ✅ DATO REAL
            },
            "billing_address": {
                "street": street,  # ✅ DATO REAL
                "city": city,  # ✅ DATO REAL
                "zip": zip_code,  # ✅ DATO REAL
                "country": "EC"  # ✅ CORREGIDO: era "ECU", debe ser ISO-2
            },
            "order": {
                "dev_reference": dev_reference,  # ✅ CORREGIDO: sin UUID
                "description": "Recarga PITIUPI",
                "amount": float(amount),  # ✅ CORREGIDO: era req.amount
                "currency": "USD",
                "vat": 0,
                "taxable_amount": float(amount),  # ✅ CORREGIDO: era req.amount
                "tax_percentage": 0,
                "installments_type": 1  # ✅ CORREGIDO: era 0, debe ser 1
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot"
            }
        }
        
        logger.info("📦 Payload Nuvei construido con datos reales")
        logger.debug(f"📋 Payload completo: {nuvei_payload}")

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
# (usado desde Postman con datos completos)
# ============================================================

@router.post("/create_payment", response_model=PaymentCreateResponse)
def create_payment(req: PaymentCreateRequest):
    """
    🔥 Endpoint de prueba / API directa
    Devuelve payment_url en JSON
    
    ⚠️ REQUIERE DATOS REALES DEL USUARIO
    """
    try:
        logger.info(f"💰 Creando pago | User: {req.telegram_id} | Amount: ${req.amount}")
        logger.info(f"📧 Email: {req.email} | 👤 Usuario: {req.name} {req.last_name}")

        # ========================================================
        # GENERACIÓN DE dev_reference (CORREGIDO)
        # ========================================================
        
        dev_reference = f"PITIUPI-{req.telegram_id}-{int(time.time())}"
        logger.info(f"🔑 dev_reference generado: {dev_reference}")

        # ========================================================
        # PAYLOAD NUVEI (CORREGIDO)
        # ========================================================

        nuvei_payload = {
            "user": {
                "id": str(req.telegram_id),
                "email": req.email,  # ✅ DATO REAL
                "name": req.name,  # ✅ DATO REAL
                "last_name": req.last_name,  # ✅ DATO REAL
                "phone_number": req.phone_number,  # ✅ DATO REAL
                "fiscal_number": req.fiscal_number,  # ✅ DATO REAL
            },
            "billing_address": {
                "street": req.street,  # ✅ DATO REAL
                "city": req.city,  # ✅ DATO REAL
                "zip": req.zip_code,  # ✅ DATO REAL
                "country": "EC",  # ✅ CORREGIDO: ISO-2
            },
            "order": {
                "dev_reference": dev_reference,  # ✅ CORREGIDO: sin UUID
                "description": "Recarga PITIUPI",
                "amount": float(req.amount),
                "currency": "USD",
                "vat": 0,
                "taxable_amount": float(req.amount),
                "tax_percentage": 0,
                "installments_type": 1,  # ✅ CORREGIDO: era 0
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
            },
        }

        logger.debug(f"📋 Payload completo: {nuvei_payload}")

        nuvei_resp = client.create_linktopay(nuvei_payload)

        if not nuvei_resp.get("success"):
            logger.error(f"❌ Error Nuvei: {nuvei_resp.get('detail')}")
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
        "version": "6.1",
        "nuvei_env": ENV,
        "corrections_applied": [
            "country: ECU -> EC (ISO-2)",
            "installments_type: 0 -> 1",
            "dev_reference: UUID -> timestamp-based",
            "req.telegram_id -> telegram_id (GET endpoint)",
            "Datos fake -> datos reales del usuario"
        ]
    }

# ============================================================
# END OF FILE
# ============================================================
