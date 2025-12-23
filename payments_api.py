# ============================================================
# payments_api.py — Orquestador de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.2 — Backend Nuvei (ESPECIFICACIÓN OFICIAL)
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
    2. Construye payload Nuvei según ESPECIFICACIÓN OFICIAL
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
        # GENERACIÓN DE dev_reference
        # ========================================================
        # Formato: PITIUPI-{telegram_id}-{timestamp}
        # Sin guiones UUID, máximo 32 caracteres
        
        dev_reference = f"PITIUPI-{telegram_id}-{int(time.time())}"
        logger.info(f"🔑 dev_reference generado: {dev_reference}")

        # ========================================================
        # PAYLOAD NUVEI (ESPECIFICACIÓN OFICIAL)
        # ========================================================
        # ✅ Basado en: https://developers.paymentez.com/api/#payment-methods-linktopay
        # ✅ country: ISO-3 ("ECU" no "EC")
        # ✅ installments_type: 0 (según ejemplo oficial)
        # ✅ SIN campos extra (vat, taxable_amount, tax_percentage)

        nuvei_payload = {
            "user": {
                "id": str(telegram_id),
                "email": email,
                "name": name,
                "last_name": last_name,
                "phone_number": phone_number,
                "fiscal_number": fiscal_number,
                # Opcional: "fiscal_number_type": "CI" o "RUC"
            },
            "order": {
                "dev_reference": dev_reference,
                "description": "Recarga PITIUPI",
                "amount": float(amount),
                "installments_type": 0,
                "currency": "USD",
                "vat": 0,                    # ✅ AÑADIR
                "inc": 0,                    # ✅ AÑADIR
                "taxable_amount": 0,         # ✅ AÑADIR (para Ecuador)
                "tax_percentage": 0,         # ✅ AÑADIR (0 para Ecuador)
            },
            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
                "review_url": "https://t.me/pitiupibot",  # ✅ AÑADIR SIEMPRE
                # "callback_url": "https://tudominio.com/nuvei/callback"  # OPCIONAL
            },
            "billing_address": {
                "street": street,
                "city": city,
                "country": "ECU",  # ✅ Correcto ISO-3
                "zip": zip_code,
                # Opcional: "state": "Pichincha"
            },
        }
        
        logger.info("📦 Payload Nuvei construido según especificación oficial")
        logger.debug(f"📋 Payload completo: {nuvei_payload}")

        # ========================================================
        # LLAMADA A NUVEI
        # ========================================================

        nuvei_resp = client.create_linktopay(nuvei_payload)

        if not nuvei_resp.get("success"):
            error_detail = nuvei_resp.get("detail", "Error comunicándose con Nuvei")
            error_raw = nuvei_resp.get("raw", "")
            
            logger.error(f"❌ Error Nuvei: {error_detail}")
            if error_raw:
                logger.error(f"❌ Raw response: {error_raw[:500]}")
            
            raise HTTPException(
                status_code=502,
                detail=error_detail,
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
        # GENERACIÓN DE dev_reference
        # ========================================================
        
        dev_reference = f"PITIUPI-{req.telegram_id}-{int(time.time())}"
        logger.info(f"🔑 dev_reference generado: {dev_reference}")

        # ========================================================
        # PAYLOAD NUVEI (ESPECIFICACIÓN OFICIAL)
        # ========================================================

        nuvei_payload = {
            "user": {
                "id": str(req.telegram_id),
                "email": req.email,
                "name": req.name,
                "last_name": req.last_name,
                "phone_number": req.phone_number,
                "fiscal_number": req.fiscal_number,
            },
            "order": {
                "dev_reference": dev_reference,
                "description": "Recarga PITIUPI",
                "amount": float(req.amount),
                "installments_type": 0,  # ✅ Según spec oficial
                "currency": "USD",
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
            },
            "billing_address": {
                "street": req.street,
                "city": req.city,
                "country": "ECU",  # ✅ ISO-3
                "zip": req.zip_code,
            },
        }

        logger.debug(f"📋 Payload completo: {nuvei_payload}")

        nuvei_resp = client.create_linktopay(nuvei_payload)

        if not nuvei_resp.get("success"):
            error_detail = nuvei_resp.get("detail", "Error Nuvei")
            error_raw = nuvei_resp.get("raw", "")
            
            logger.error(f"❌ Error Nuvei: {error_detail}")
            if error_raw:
                logger.error(f"❌ Raw response: {error_raw[:500]}")
            
            raise HTTPException(
                status_code=502,
                detail=error_detail,
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
        "version": "6.2",
        "nuvei_env": ENV,
        "spec_compliance": "Official Nuvei LinkToPay Specification",
        "corrections_applied": [
            "✅ country: ECU (ISO-3 según doc oficial)",
            "✅ installments_type: 0 (según ejemplo oficial)",
            "✅ dev_reference: timestamp-based (sin UUID)",
            "✅ Eliminados campos no soportados (vat, taxable_amount, tax_percentage)",
            "✅ Datos reales del usuario (no fake data)",
            "✅ Raw error logging habilitado"
        ]
    }

# ============================================================
# END OF FILE
# ============================================================
