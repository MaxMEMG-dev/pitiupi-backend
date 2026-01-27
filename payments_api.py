# ============================================================
# payments_api.py — Orquestador de Pagos (Versión Stripe)
# PITIUPI v6.4 — Reemplazo de Nuvei por Stripe Checkout
# ============================================================

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
import stripe
import os
import logging
import uuid

# Config DB (Opcional)
try:
    from database.session import SessionLocal
    from database.models.payment_intents import PaymentIntent
    from database.models.user import User
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

router = APIRouter(tags=["Payments"])
logger = logging.getLogger("payments-api")

# Configuración Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
SUCCESS_URL = "https://t.me/pitiupibot" # O tu página de gracias
CANCEL_URL = "https://t.me/pitiupibot"

# --- MODELOS SIMPLIFICADOS (Stripe hace el trabajo pesado) ---
class PaymentCreateRequest(BaseModel):
    telegram_id: int = Field(..., description="ID Usuario")
    amount: float = Field(..., gt=0.50, description="Monto USD (Min $0.50)")
    email: str = Field(None, description="Opcional para pre-llenar")

class PaymentResponse(BaseModel):
    success: bool
    payment_url: str
    session_id: str

# --- ENDPOINTS ---

@router.get("/pay")
async def pay_redirect(
    telegram_id: int = Query(...),
    amount: float = Query(...)
):
    """
    Genera un link de Stripe Checkout y redirige al usuario.
    Uso: Bot Telegram envía al usuario a este link.
    """
    try:
        # 1. Crear Sesión de Stripe
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Recarga Saldo PITIUPI',
                    },
                    'unit_amount': int(amount * 100), # Centavos
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            client_reference_id=str(telegram_id), # CLAVE: Para el webhook
            metadata={
                'user_id': str(telegram_id),
                'source': 'bot_api_redirect'
            }
        )
        
        # 2. Guardar Intención en DB (Opcional, para traza)
        if DB_AVAILABLE:
            _save_intent_placeholder(telegram_id, session.id, amount)

        logger.info(f"🔗 Link Stripe generado para {telegram_id}: {session.url}")
        return RedirectResponse(url=session.url)

    except Exception as e:
        logger.error(f"❌ Error creando sesión Stripe: {e}")
        raise HTTPException(status_code=500, detail="Error generando pago")

@router.post("/create_payment", response_model=PaymentResponse)
def create_payment(req: PaymentCreateRequest):
    """API JSON para generar links de pago."""
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': 'Recarga PITIUPI'},
                    'unit_amount': int(req.amount * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            client_reference_id=str(req.telegram_id),
            metadata={'user_id': str(req.telegram_id)},
            customer_email=req.email
        )
        
        return {
            "success": True, 
            "payment_url": session.url, 
            "session_id": session.id
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _save_intent_placeholder(tid, pid, amount):
    """Guarda un registro PENDING básico en DB"""
    try:
        db = SessionLocal()
        # Lógica simplificada de guardado...
        # (Implementar similar al save_payment_to_db original si se requiere auditoría pre-pago)
        db.close()
    except:
        pass
