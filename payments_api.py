# ============================================================
# payments_api.py — Creación de LinkToPay Nuvei (Ecuador)
# PITIUPI v6.0 — 100% V6-Compliant + FastAPI
# ============================================================

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator, Field
import os
import logging
from typing import Optional

from database.session import get_db
from database.services import payments_service
from database.crud import payments_crud, user_crud
from nuvei_client import NuveiClient

router = APIRouter(tags=["Payments"])
logger = logging.getLogger(__name__)


# ============================================================
# CREDENCIALES NUVEI
# ============================================================
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
ENV = os.getenv("NUVEI_ENV", "stg")

if not APP_CODE or not APP_KEY:
    logger.critical("❌ Credenciales Nuvei no configuradas")
    raise RuntimeError("NUVEI_APP_CODE_SERVER y NUVEI_APP_KEY_SERVER son obligatorios")

client = NuveiClient(
    app_code=APP_CODE,
    app_key=APP_KEY,
    environment=ENV,
)


# ============================================================
# MODELOS PYDANTIC
# ============================================================
class PaymentCreateRequest(BaseModel):
    """
    V6: Request para crear un pago con Nuvei
    
    Attributes:
        telegram_id: ID de Telegram del usuario
        amount: Monto en USD (debe ser positivo y <= 10,000)
    """
    telegram_id: int = Field(..., gt=0, description="Telegram ID del usuario")
    amount: float = Field(..., gt=0, le=10000, description="Monto en USD")

    @validator("amount")
    def validate_amount(cls, v):
        """Validación adicional de monto"""
        if v <= 0:
            raise ValueError("El monto debe ser mayor a 0")
        if v > 10000:
            raise ValueError("El monto no puede exceder $10,000")
        return round(v, 2)  # Redondear a 2 decimales


class PaymentCreateResponse(BaseModel):
    """
    V6: Response de creación de pago
    
    Attributes:
        success: Si la operación fue exitosa
        intent_uuid: UUID del PaymentIntent creado
        intent_id: ID numérico del PaymentIntent
        order_id: ID de orden de Nuvei
        payment_url: URL de pago de Nuvei (LinkToPay)
    """
    success: bool
    intent_uuid: str
    intent_id: int
    order_id: str
    payment_url: str


class PaymentIntentResponse(BaseModel):
    """
    V6: Response de consulta de PaymentIntent
    
    Attributes:
        success: Si la operación fue exitosa
        intent: Datos del PaymentIntent
    """
    success: bool
    intent: dict


# ============================================================
# VALIDACIÓN DE PERFIL DE USUARIO
# ============================================================
def validate_user_profile(user) -> tuple[bool, Optional[str]]:
    """
    V6: Valida que el usuario tenga perfil completo para Nuvei
    
    Args:
        user: Instancia del modelo User
    
    Returns:
        Tuple[is_valid, error_message]
    
    Note:
        - Nuvei requiere: email, phone, document_number, name, city, country
        - Ecuador requiere fiscal_number (cédula)
    """
    required_fields = {
        "email": user.email,
        "phone": user.phone,
        "document_number": user.document_number,
        "telegram_first_name": user.telegram_first_name,
        "city": user.city,
        "country": user.country,
    }
    
    missing = [field for field, value in required_fields.items() if not value]
    
    if missing:
        return False, f"Perfil incompleto. Complete: {', '.join(missing)} en el bot"
    
    return True, None


# ============================================================
# CONSTRUCCIÓN DE PAYLOAD NUVEI
# ============================================================
def build_nuvei_payload(user, amount: float, intent_uuid: str) -> dict:
    """
    V6: Construye el payload para Nuvei LinkToPay
    
    Args:
        user: Instancia del modelo User
        amount: Monto en USD
        intent_uuid: UUID del PaymentIntent (para webhook)
    
    Returns:
        dict: Payload listo para enviar a Nuvei
    
    Note:
        - user.id debe ser STRING para Nuvei (usado en STOKEN)
        - dev_reference = UUID (NO ID numérico, para webhook)
        - expiration_time = 15 minutos (900 segundos)
        - country = "ECU" (código ISO de Ecuador)
        
    CRÍTICO V6:
        - dev_reference DEBE ser UUID para que el webhook funcione
        - El webhook busca PaymentIntent con get_by_uuid(dev_reference)
    """
    return {
        "user": {
            "id": str(user.telegram_id),  # CRÍTICO: String para STOKEN
            "email": user.email,
            "name": user.telegram_first_name,
            "last_name": user.telegram_last_name or user.telegram_first_name,
            "phone_number": user.phone,
            "fiscal_number": user.document_number,
        },
        "billing_address": {
            "street": "Sin calle",  # Campo obligatorio pero no usado
            "city": user.city,
            "zip": "000000",
            "country": "ECU",  # Ecuador
        },
        "order": {
            "dev_reference": intent_uuid,  # ✅ UUID para webhook
            "description": "Recarga PITIUPI",
            "amount": float(amount),
            "currency": "USD",
            "installments_type": 0,  # Sin cuotas
            "vat": 0,
            "taxable_amount": float(amount),
            "tax_percentage": 0,
        },
        "configuration": {
            "partial_payment": False,
            "expiration_time": 900,  # 15 minutos
            "allowed_payment_methods": ["All"],
            "success_url": "https://t.me/pitiupibot?start=payment_success",
            "failure_url": "https://t.me/pitiupibot?start=payment_failed",
            "pending_url": "https://t.me/pitiupibot?start=payment_pending",
            "review_url": "https://t.me/pitiupibot?start=payment_review",
        },
    }


# ============================================================
# POST /payments/create_payment
# ============================================================
@router.post("/create_payment", response_model=PaymentCreateResponse)
def create_payment(
    req: PaymentCreateRequest,
    session: Session = Depends(get_db)
):
    """
    V6: Crea un PaymentIntent y genera LinkToPay de Nuvei
    
    FLUJO V6:
    1. Validar usuario existe
    2. Validar perfil completo (email, phone, etc.)
    3. payments_service.create_payment_intent_service()
    4. nuvei_client.create_linktopay()
    5. payments_crud.update_provider_intent_id()
    6. payments_crud.update_redirect_url()
    
    Args:
        req: PaymentCreateRequest (telegram_id + amount)
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        PaymentCreateResponse con intent_uuid, order_id, payment_url
    
    Raises:
        404: Usuario no encontrado
        400: Perfil incompleto o validación fallida
        502: Error en pasarela Nuvei
        500: Error interno
    
    Note:
        - NO toca balances (eso lo hace el webhook al confirmar)
        - NO hace commit aquí (lo hace el middleware)
        - Idempotente: se puede reintentar si falla Nuvei
    """
    try:
        logger.info(
            f"💰 Creando pago | TelegramID={req.telegram_id} | Amount=${req.amount:.2f}"
        )

        # ============================================================
        # 1️⃣ VALIDAR USUARIO EXISTE
        # ============================================================
        user = user_crud.get_user_by_telegram_id(req.telegram_id, session=session)
        if not user:
            logger.warning(f"⚠️ Usuario Telegram {req.telegram_id} no encontrado")
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        # ============================================================
        # 2️⃣ VALIDAR PERFIL COMPLETO
        # ============================================================
        is_valid, error_message = validate_user_profile(user)
        if not is_valid:
            logger.warning(
                f"⚠️ Perfil incompleto | TelegramID={req.telegram_id} | {error_message}"
            )
            raise HTTPException(status_code=400, detail=error_message)

        # ============================================================
        # 2.5️⃣ IDEMPOTENCIA: Reutilizar intent pendiente reciente (opcional)
        # ============================================================
        # V6: Si existe un intent PENDING reciente con mismo monto, reutilizarlo
        existing_intent = payments_crud.get_latest_pending_by_user_and_amount(
            user_id=user.id,
            amount=req.amount,
            session=session
        )
        
        if existing_intent and existing_intent.redirect_url:
            logger.info(
                f"🔁 Reutilizando PaymentIntent existente: UUID={existing_intent.uuid}"
            )
            return PaymentCreateResponse(
                success=True,
                intent_uuid=existing_intent.uuid,
                intent_id=existing_intent.id,
                order_id=existing_intent.details.get("nuvei_order_id", ""),
                payment_url=existing_intent.redirect_url,
            )

        # ============================================================
        # 3️⃣ CREAR PAYMENT INTENT (V6 SERVICE)
        # ============================================================
        intent_data = payments_service.create_payment_intent_service(
            user_id=user.id,
            amount=req.amount,
            session=session
        )
        
        intent_uuid = intent_data["uuid"]
        intent_id = intent_data["id"]
        
        logger.info(f"📝 PaymentIntent creado: UUID={intent_uuid} | ID={intent_id}")

        # ============================================================
        # 4️⃣ CONSTRUIR PAYLOAD NUVEI (UUID como dev_reference)
        # ============================================================
        nuvei_payload = build_nuvei_payload(
            user=user,
            amount=req.amount,
            intent_uuid=intent_uuid  # ✅ UUID para webhook
        )
        
        logger.info(f"📤 Enviando a Nuvei | Intent={intent_id}")

        # ============================================================
        # 5️⃣ LLAMAR A NUVEI (HTTP CLIENT)
        # ============================================================
        nuvei_resp = client.create_linktopay(nuvei_payload)
        
        if not nuvei_resp.get("success"):
            error_detail = nuvei_resp.get("detail", "Error desconocido en pasarela")
            logger.error(f"❌ Error Nuvei: {error_detail} | Response: {nuvei_resp}")
            raise HTTPException(
                status_code=502,
                detail=f"Error en pasarela de pago: {error_detail}"
            )

        # ============================================================
        # 6️⃣ EXTRAER RESPUESTA DE NUVEI
        # ============================================================
        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error(f"❌ Respuesta incompleta de Nuvei: {nuvei_resp}")
            raise HTTPException(
                status_code=500,
                detail="Respuesta incompleta de la pasarela de pago"
            )

        # ============================================================
        # 7️⃣ ACTUALIZAR PAYMENT INTENT CON DATOS DE NUVEI (V6 CRUD)
        # ============================================================
        intent = payments_crud.get_by_uuid(intent_uuid, session=session)
        
        # V6: Guardar order_id en details (metadata) + URL de pago
        # NO usar provider_intent_id aquí (ese campo es para transaction_id del webhook)
        if not intent.details:
            intent.details = {}
        intent.details["nuvei_order_id"] = order_id
        intent.details["nuvei_ltp_created_at"] = data.get("order", {}).get("created_at")
        
        # Guardar URL de pago en campo dedicado
        payments_crud.update_redirect_url(
            intent=intent,
            redirect_url=payment_url,
            session=session
        )
        
        session.flush()
        
        logger.info(
            f"✅ LinkToPay creado | UUID={intent_uuid} | Order={order_id} | URL={payment_url[:50]}..."
        )

        # ============================================================
        # 8️⃣ RETORNAR RESPUESTA
        # ============================================================
        return PaymentCreateResponse(
            success=True,
            intent_uuid=intent_uuid,
            intent_id=intent_id,
            order_id=order_id,
            payment_url=payment_url,
        )

    except HTTPException:
        raise
    
    except ValueError as e:
        logger.error(f"❌ Error de validación: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# ============================================================
# GET /payments/intent/{intent_uuid}
# ============================================================
@router.get("/intent/{intent_uuid}", response_model=PaymentIntentResponse)
def get_intent_by_uuid(
    intent_uuid: str,
    session: Session = Depends(get_db)
):
    """
    V6: Obtiene un PaymentIntent por UUID
    
    Args:
        intent_uuid: UUID del PaymentIntent
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        PaymentIntentResponse con datos del intent
    
    Raises:
        404: PaymentIntent no encontrado
        500: Error interno
    
    Note:
        - Solo lectura (no muta estado)
        - Útil para tracking desde el bot
    """
    try:
        intent = payments_crud.get_by_uuid(intent_uuid, session=session)
        
        if not intent:
            logger.warning(f"⚠️ PaymentIntent UUID {intent_uuid} no encontrado")
            raise HTTPException(status_code=404, detail="Payment intent no encontrado")
        
        # Serializar a dict (evitar exponer modelo SQLAlchemy directamente)
        intent_dict = {
            "id": intent.id,
            "uuid": intent.uuid,
            "user_id": intent.user_id,
            "provider": intent.provider,
            "provider_intent_id": intent.provider_intent_id,
            "amount": float(intent.amount),
            "amount_received": float(intent.amount_received) if intent.amount_received else None,
            "currency": intent.currency,
            "status": intent.status.value if hasattr(intent.status, 'value') else str(intent.status),
            "redirect_url": intent.redirect_url,
            "created_at": intent.created_at.isoformat() if intent.created_at else None,
        }
        
        return PaymentIntentResponse(
            success=True,
            intent=intent_dict
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Error obteniendo intent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# ============================================================
# GET /payments/intent/by_id/{intent_id}
# ============================================================
@router.get("/intent/by_id/{intent_id}", response_model=PaymentIntentResponse)
def get_intent_by_id(
    intent_id: int,
    session: Session = Depends(get_db)
):
    """
    V6: Obtiene un PaymentIntent por ID numérico
    
    Args:
        intent_id: ID numérico del PaymentIntent
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        PaymentIntentResponse con datos del intent
    
    Raises:
        404: PaymentIntent no encontrado
        500: Error interno
    
    Note:
        - Endpoint legacy para compatibilidad
        - Preferir usar UUID en nuevos desarrollos
    """
    try:
        intent = payments_crud.get_by_id(intent_id, session=session)
        
        if not intent:
            logger.warning(f"⚠️ PaymentIntent ID {intent_id} no encontrado")
            raise HTTPException(status_code=404, detail="Payment intent no encontrado")
        
        # Serializar a dict
        intent_dict = {
            "id": intent.id,
            "uuid": intent.uuid,
            "user_id": intent.user_id,
            "provider": intent.provider,
            "provider_intent_id": intent.provider_intent_id,
            "amount": float(intent.amount),
            "amount_received": float(intent.amount_received) if intent.amount_received else None,
            "currency": intent.currency,
            "status": intent.status.value if hasattr(intent.status, 'value') else str(intent.status),
            "redirect_url": intent.redirect_url,
            "created_at": intent.created_at.isoformat() if intent.created_at else None,
        }
        
        return PaymentIntentResponse(
            success=True,
            intent=intent_dict
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Error obteniendo intent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del servidor")
