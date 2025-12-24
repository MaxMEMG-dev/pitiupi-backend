# ============================================================
# payments_api.py — Orquestador de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.3 — Backend Nuvei + DB Integration
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
import os
import logging
import time
import uuid
import requests

# ========================================================
# 🔥 IMPORTS PARA BASE DE DATOS
# ========================================================
try:
    from database.session import SessionLocal
    from database.models.payment_intents import PaymentIntent, PaymentIntentStatus
    from database.models.user import User
    DB_AVAILABLE = True
    logger_db = logging.getLogger(__name__)
    logger_db.info("✅ Módulos de base de datos importados correctamente")
except ImportError as e:
    DB_AVAILABLE = False
    logger_db = logging.getLogger(__name__)
    logger_db.warning(f"⚠️ No se pudieron importar módulos de DB: {e}")
    logger_db.warning("⚠️ Backend funcionará en modo stateless (sin guardar en DB)")
# ========================================================

from nuvei_client import NuveiClient

router = APIRouter(tags=["Payments"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO (Render)
# ============================================================

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")  # URL del bot para notificaciones

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
logger.info(f"✅ Base de datos: {'DISPONIBLE' if DB_AVAILABLE else 'NO DISPONIBLE (modo stateless)'}")

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
# FUNCIÓN HELPER: GUARDAR EN DB
# ============================================================

def save_payment_to_db(
    telegram_id: int,
    order_id: str,
    amount: float,
    email: str,
    dev_reference: str,
    name: str,
    last_name: str,
    phone_number: str,
    fiscal_number: str
) -> bool:
    """
    Intenta guardar el payment intent en la base de datos.
    Retorna True si tuvo éxito, False en caso contrario.
    """
    if not DB_AVAILABLE:
        logger.warning("⚠️ DB no disponible, no se guardará el payment intent")
        return False
    
    db = SessionLocal()
    try:
        # Buscar usuario por telegram_id
        user = db.query(User).filter(User.telegram_id == str(telegram_id)).first()
        
        if not user:
            logger.error(f"❌ Usuario con telegram_id={telegram_id} no existe en DB")
            return False
        
        # Crear payment intent
        new_intent = PaymentIntent(
            uuid=uuid.uuid4(),
            user_id=user.id,
            amount=float(amount),
            currency="USD",
            provider="nuvei",
            provider_order_id=order_id,
            status=PaymentIntentStatus.PENDING,
            details={
                "email": email,
                "dev_reference": dev_reference,
                "name": name,
                "last_name": last_name,
                "phone_number": phone_number,
                "fiscal_number": fiscal_number
            }
        )
        
        db.add(new_intent)
        db.commit()
        db.refresh(new_intent)
        
        logger.info(f"💾 ✅ Payment intent guardado | order_id={order_id} | user_id={user.id}")
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error al guardar en DB: {e}", exc_info=True)
        return False
    finally:
        db.close()


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
    🔥 Flujo directo de pago

    1. Recibe datos completos del usuario
    2. Construye payload Nuvei según ESPECIFICACIÓN OFICIAL
    3. Llama a LinkToPay
    4. 💾 GUARDA LA ORDEN EN LA BASE DE DATOS (si está disponible)
    5. Redirige al checkout
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
        dev_reference = f"PITIUPI-{telegram_id}-{int(time.time())}"
        logger.info(f"🔑 dev_reference generado: {dev_reference}")

        # ========================================================
        # PAYLOAD NUVEI (ESPECIFICACIÓN OFICIAL)
        # ========================================================
        nuvei_payload = {
            "user": {
                "id": str(telegram_id),
                "email": email,
                "name": name,
                "last_name": last_name,
                "phone_number": phone_number,
                "fiscal_number": fiscal_number,
            },
            "order": {
                "dev_reference": dev_reference,
                "description": "Recarga PITIUPI",
                "amount": float(amount),
                "installments_type": 0,
                "currency": "USD",
                "vat": 0,
                "inc": 0,
                "taxable_amount": 0,
                "tax_percentage": 0,
            },
            "configuration": {
                "partial_payment": False,
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
                "review_url": "https://t.me/pitiupibot",
            },
            "billing_address": {
                "street": street,
                "city": city,
                "country": "ECU",
                "zip": zip_code,
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
        
        # ========================================================
        # VALIDACIÓN ROBUSTA DE LA RESPUESTA
        # ========================================================
        if "order" not in data:
            logger.error(f"❌ Campo 'order' faltante en respuesta Nuvei")
            logger.error(f"📊 Respuesta completa: {data}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (campo 'order' faltante)",
            )
        
        if not isinstance(data["order"], dict):
            logger.error(f"❌ Campo 'order' no es un diccionario: {type(data['order'])}")
            logger.error(f"📊 Valor de 'order': {data['order']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (estructura 'order' incorrecta)",
            )
        
        if "id" not in data["order"]:
            logger.error(f"❌ Campo 'id' faltante dentro de 'order'")
            logger.error(f"📊 Estructura 'order': {data['order']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (ID de orden faltante)",
            )
        
        if "payment" not in data:
            logger.error(f"❌ Campo 'payment' faltante en respuesta Nuvei")
            logger.error(f"📊 Respuesta completa: {data}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (campo 'payment' faltante)",
            )
        
        if not isinstance(data["payment"], dict):
            logger.error(f"❌ Campo 'payment' no es un diccionario: {type(data['payment'])}")
            logger.error(f"📊 Valor de 'payment': {data['payment']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (estructura 'payment' incorrecta)",
            )
        
        if "payment_url" not in data["payment"]:
            logger.error(f"❌ Campo 'payment_url' faltante dentro de 'payment'")
            logger.error(f"📊 Estructura 'payment': {data['payment']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (URL de pago faltante)",
            )
        
        # Extraer valores
        order_id = data["order"]["id"]
        payment_url = data["payment"]["payment_url"]

        logger.info(f"✅ LinkToPay creado | Order ID: {order_id}")
        logger.info(f"🔗 Payment URL: {payment_url}")

        # ========================================================
        # 💾 GUARDADO EN BASE DE DATOS
        # ========================================================
        db_saved = save_payment_to_db(
            telegram_id=telegram_id,
            order_id=order_id,
            amount=amount,
            email=email,
            dev_reference=dev_reference,
            name=name,
            last_name=last_name,
            phone_number=phone_number,
            fiscal_number=fiscal_number
        )
        
        if db_saved:
            logger.info(f"💾 ✅ Payment intent guardado exitosamente")
        else:
            logger.warning(f"⚠️ Payment intent NO guardado (continuando flujo)")
        
        logger.info("=" * 60)

        return RedirectResponse(url=payment_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error crítico en pay_redirect: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor")


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
                "installments_type": 0,
                "currency": "USD",
                "vat": 0,
                "inc": 0,
                "taxable_amount": float(req.amount),
                "tax_percentage": 0,
            },
            "configuration": {
                "expiration_time": 900,
                "allowed_payment_methods": ["All"],
                "success_url": "https://t.me/pitiupibot",
                "failure_url": "https://t.me/pitiupibot",
                "pending_url": "https://t.me/pitiupibot",
                "review_url": "https://t.me/pitiupibot",
            },
            "billing_address": {
                "street": req.street,
                "city": req.city,
                "country": "ECU",
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
        
        # ========================================================
        # VALIDACIÓN ROBUSTA DE LA RESPUESTA
        # ========================================================
        if "order" not in data:
            logger.error(f"❌ Campo 'order' faltante en respuesta Nuvei")
            logger.error(f"📊 Respuesta completa: {data}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (campo 'order' faltante)",
            )
        
        if not isinstance(data["order"], dict):
            logger.error(f"❌ Campo 'order' no es un diccionario: {type(data['order'])}")
            logger.error(f"📊 Valor de 'order': {data['order']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (estructura 'order' incorrecta)",
            )
        
        if "id" not in data["order"]:
            logger.error(f"❌ Campo 'id' faltante dentro de 'order'")
            logger.error(f"📊 Estructura 'order': {data['order']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (ID de orden faltante)",
            )
        
        if "payment" not in data:
            logger.error(f"❌ Campo 'payment' faltante en respuesta Nuvei")
            logger.error(f"📊 Respuesta completa: {data}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (campo 'payment' faltante)",
            )
        
        if not isinstance(data["payment"], dict):
            logger.error(f"❌ Campo 'payment' no es un diccionario: {type(data['payment'])}")
            logger.error(f"📊 Valor de 'payment': {data['payment']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (estructura 'payment' incorrecta)",
            )
        
        if "payment_url" not in data["payment"]:
            logger.error(f"❌ Campo 'payment_url' faltante dentro de 'payment'")
            logger.error(f"📊 Estructura 'payment': {data['payment']}")
            raise HTTPException(
                status_code=502,
                detail="Respuesta inválida de Nuvei (URL de pago faltante)",
            )
        
        # Extraer valores
        order_id = data["order"]["id"]
        payment_url = data["payment"]["payment_url"]

        logger.info(f"✅ Link generado | Order ID: {order_id}")
        logger.info(f"🔗 Payment URL: {payment_url}")

        # ========================================================
        # 💾 GUARDADO EN BASE DE DATOS
        # ========================================================
        db_saved = save_payment_to_db(
            telegram_id=req.telegram_id,
            order_id=order_id,
            amount=req.amount,
            email=req.email,
            dev_reference=dev_reference,
            name=req.name,
            last_name=req.last_name,
            phone_number=req.phone_number,
            fiscal_number=req.fiscal_number
        )
        
        if db_saved:
            logger.info(f"💾 ✅ Payment intent guardado exitosamente")
        else:
            logger.warning(f"⚠️ Payment intent NO guardado (continuando flujo)")

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
        "version": "6.3",
        "nuvei_env": ENV,
        "database_mode": "CONNECTED" if DB_AVAILABLE else "STATELESS",
        "spec_compliance": "Official Nuvei LinkToPay Specification",
        "features": [
            "✅ LinkToPay creation",
            "✅ Robust response validation",
            "✅ DB integration (optional)" if DB_AVAILABLE else "⚠️ DB not available (stateless mode)",
            "✅ Error logging with raw responses",
            "✅ ISO-3 country codes (ECU)",
            "✅ Timestamp-based dev_reference"
        ]
    }

# ============================================================
# END OF FILE
# ============================================================
