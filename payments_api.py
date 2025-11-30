from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import logging

from payments_core import (
    create_payment_intent,
    update_payment_intent,
    get_payment_intent
)
from nuvei_client import NuveiClient

router = APIRouter()
logger = logging.getLogger(__name__)

# Cargar credenciales SIN VALIDACIÓN QUE BLOQUEE
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER") 
ENV = os.getenv("NUVEI_ENV", "stg")

logger.info(f"🔧 Configuración Nuvei:")
logger.info(f"   APP_CODE: {'✅' if APP_CODE else '❌'} {APP_CODE[:8] if APP_CODE else 'NO CONFIGURADA'}...")
logger.info(f"   APP_KEY: {'✅' if APP_KEY else '❌'} {APP_KEY[:8] if APP_KEY else 'NO CONFIGURADA'}...")
logger.info(f"   ENV: {ENV}")

# Inicializar cliente sin fallar
client = NuveiClient(APP_CODE, APP_KEY, environment=ENV)

class PaymentCreateRequest(BaseModel):
    telegram_id: int
    amount: float

@router.get("/debug/env")
def debug_env():
    """Endpoint para debug de variables de entorno"""
    return {
        "NUVEI_APP_CODE_SERVER": os.getenv("NUVEI_APP_CODE_SERVER", "❌ NO CONFIGURADA"),
        "NUVEI_APP_KEY_SERVER": os.getenv("NUVEI_APP_KEY_SERVER", "❌ NO CONFIGURADA"), 
        "NUVEI_ENV": os.getenv("NUVEI_ENV", "❌ NO CONFIGURADA"),
        "DATABASE_URL": "✅ CONFIGURADA" if os.getenv("DATABASE_URL") else "❌ NO CONFIGURADA",
        "status": "Backend funcionando - Verifica variables en Render Dashboard"
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

        logger.info(f"💰 Creando pago para user {req.telegram_id}, amount {req.amount}")

        # Crear intent interno
        intent_id = create_payment_intent(
            user_id=req.telegram_id,
            amount=req.amount
        )

        amount = float(req.amount)

        order_data = {
            "user": {
                "id": str(req.telegram_id),
                "email": f"user{req.telegram_id}@pitiupi.com",
                "name": "User",
                "last_name": str(req.telegram_id)
            },
            "order": {
                "dev_reference": str(intent_id),
                "description": "Recarga Pitiupi",
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
                "success_url": "https://pitiupi.com/success",
                "failure_url": "https://pitiupi.com/failure",
                "pending_url": "https://pitiupi.com/pending",
                "review_url": "https://pitiupi.com/review"
            }
        }

        logger.info(f"📤 Enviando a Nuvei con: {order_data}")

        # Llamar a Nuvei
        nuvei_resp = client.create_linktopay(order_data)

        logger.info(f"🔎 Respuesta cruda Nuvei: {nuvei_resp}")

        # PRODUCCIÓN: validación correcta
        if not nuvei_resp.get("success"):
            detail = nuvei_resp.get("detail") or nuvei_resp.get("message") or "Error desconocido en Nuvei"
            logger.error(f"❌ Nuvei error: {detail}")
            raise HTTPException(status_code=500, detail=f"Error Nuvei: {detail}")

        data = nuvei_resp.get("data", {})
        order_id = data.get("order", {}).get("id")
        payment_url = data.get("payment", {}).get("payment_url")

        if not order_id or not payment_url:
            logger.error(f"❌ Nuvei devolvió datos incompletos: {nuvei_resp}")
            raise HTTPException(status_code=500, detail="Nuvei no devolvió order_id o payment_url")

        # Guardar order_id
        update_payment_intent(intent_id, order_id=order_id)

        logger.info(f"✅ Pago creado: intent={intent_id}, order={order_id}")

        return {
            "intent_id": intent_id,
            "order_id": order_id,
            "payment_url": payment_url
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ ERROR /create_payment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno creando pago")


@router.get("/check_payment/{intent_id}")
def check_payment(intent_id: int):
    """Consulta Nuvei para validar si el pago fue aprobado."""
    try:
        intent = get_payment_intent(intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent no encontrado")

        order_id = intent["order_id"]
        if not order_id:
            raise HTTPException(status_code=400, detail="Intent sin order_id asignado")

        nuvei_status = client.verify_transaction(order_id)
        
        if nuvei_status.get("status") == "error":
            return {"paid": False}
            
        transaction = nuvei_status.get("transaction", {})
        status = transaction.get("status")
        detail = transaction.get("status_detail")

        if status == "success" and detail == 3:
            from payments_core import mark_intent_paid
            mark_intent_paid(
                intent_id, 
                transaction.get("id", ""),
                detail,
                transaction.get("authorization_code", "")
            )
            return {"paid": True}

        return {"paid": False}
    
    except Exception as e:
        logger.error(f"❌ ERROR /check_payment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error verificando pago")
