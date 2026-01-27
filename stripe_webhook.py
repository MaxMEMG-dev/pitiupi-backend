# ============================================================
# stripe_webhook.py — Receptor de Webhooks Stripe
# PITIUPI v6.5 — Adaptación de lógica Nuvei a Stripe
# ============================================================

import stripe
from fastapi import APIRouter, Request, HTTPException, Header
import logging
import os
import json
import requests
from decimal import Decimal
from typing import Optional

# Intentos de importación de DB
HAS_DB = False
try:
    from database.session import db_session
    from database.models.user import User
    from sqlalchemy import select, text
    HAS_DB = True
except ImportError as e:
    pass

router = APIRouter(tags=["Stripe"])
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stripe-webhook")

# Variables de entorno
STRIPE_API_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Verificar configuración
if not STRIPE_API_KEY:
    logger.error("❌ STRIPE_SECRET_KEY no configurada")
if not STRIPE_WEBHOOK_SECRET:
    logger.error("❌ STRIPE_WEBHOOK_SECRET no configurada")

stripe.api_key = STRIPE_API_KEY

# --- HELPERS ---

def send_telegram_notification(chat_id: int, text_msg: str):
    """Envía notificación al usuario vía Telegram."""
    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN no configurado, notificación omitida")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(
            url, 
            json={"chat_id": chat_id, "text": text_msg, "parse_mode": "HTML"}, 
            timeout=5
        )
        logger.info(f"✅ Notificación enviada a {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error notificación Telegram: {e}")

# --- WEBHOOK ---

@router.post("/callback")
async def stripe_callback(
    request: Request, 
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature")
):
    """
    Procesa eventos 'checkout.session.completed' de Stripe.
    Mantiene idempotencia y lógica AML.
    """
    
    # Log de debugging
    logger.info("📨 Webhook recibido de Stripe")
    
    payload = await request.body()
    event = None

    # 1. VERIFICACIÓN DE FIRMA
    if not stripe_signature:
        logger.error("❌ Header Stripe-Signature faltante")
        raise HTTPException(status_code=400, detail="Missing signature header")
    
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("❌ STRIPE_WEBHOOK_SECRET no configurada en el servidor")
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
        logger.info(f"✅ Firma válida - Evento: {event['type']}")
    except ValueError as e:
        logger.error(f"❌ Payload inválido: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"❌ Firma Stripe inválida: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. FILTRADO DE EVENTOS
    if event['type'] != 'checkout.session.completed':
        logger.info(f"ℹ️ Evento ignorado: {event['type']}")
        return {"status": "ignored", "type": event['type']}

    session = event['data']['object']
    
    # 3. EXTRACCIÓN DE DATOS
    transaction_id = session.get('id')
    payment_intent_id = session.get('payment_intent')
    amount_cents = session.get('amount_total', 0)
    amount_dollars = Decimal(amount_cents) / 100
    currency = session.get('currency', 'usd').upper()
    
    # Metadata crítica
    metadata = session.get('metadata', {})
    user_id_param = metadata.get('user_id') or session.get('client_reference_id')
    
    logger.info(
        f"📥 Stripe Payment: {transaction_id} | "
        f"User: {user_id_param} | Amount: ${amount_dollars} {currency}"
    )

    if not user_id_param:
        logger.error("❌ Webhook recibido sin User ID en metadata")
        return {"status": "error", "message": "missing_user_metadata"}

    # 4. PROCESAMIENTO EN BASE DE DATOS
    if not HAS_DB:
        logger.warning("⚠️ Base de datos no disponible")
        return {"status": "error", "message": "database_unavailable"}

    with db_session() as db:
        try:
            # A. IDEMPOTENCIA
            existing_intent = db.execute(
                text("""
                    SELECT id, status FROM payment_intents 
                    WHERE provider_order_id = :order_id 
                    FOR UPDATE
                """),
                {"order_id": transaction_id}
            ).fetchone()

            if existing_intent and existing_intent.status == 'COMPLETED':
                logger.info(f"✅ Pago ya procesado (Idempotencia): {transaction_id}")
                return {"status": "OK", "message": "already_processed"}

            # B. BUSCAR USUARIO
            user = db.query(User).filter(User.telegram_id == str(user_id_param)).first()
            
            if not user:
                # Intento por ID interno
                try:
                    user = db.query(User).filter(User.id == int(user_id_param)).first()
                except:
                    pass
            
            if not user:
                logger.error(f"❌ Usuario no encontrado: {user_id_param}")
                return {"status": "error", "message": "user_not_found"}

            # Bloqueo de fila
            stmt = select(User).where(User.id == user.id).with_for_update()
            user_locked = db.execute(stmt).scalar_one()

            # C. INSERTAR O ACTUALIZAR PAYMENT INTENT
            if not existing_intent:
                db.execute(
                    text("""
                        INSERT INTO payment_intents (
                            uuid, user_id, amount, amount_received, status, 
                            provider_order_id, provider, currency, details,
                            created_at, updated_at, completed_at, webhook_payload
                        ) VALUES (
                            gen_random_uuid(), :uid, :amt, :amt, 'COMPLETED',
                            :pid, 'stripe', :curr, :dets,
                            NOW(), NOW(), NOW(), :payload
                        )
                    """),
                    {
                        "uid": user_locked.id,
                        "amt": amount_dollars,
                        "pid": transaction_id,
                        "curr": currency,
                        "dets": json.dumps({"payment_intent": payment_intent_id}),
                        "payload": json.dumps(event)
                    }
                )
            else:
                db.execute(
                    text("""
                        UPDATE payment_intents 
                        SET status = 'COMPLETED', 
                            amount_received = :amount,
                            completed_at = NOW(),
                            updated_at = NOW(),
                            webhook_payload = :payload
                        WHERE provider_order_id = :order_id
                    """),
                    {
                        "amount": amount_dollars, 
                        "order_id": transaction_id, 
                        "payload": json.dumps(event)
                    }
                )

            # D. ACTUALIZAR SALDOS
            # Usar balance_available en lugar de balance_recharge si es lo que usa tu bot
            new_available = (user_locked.balance_available or Decimal(0)) + amount_dollars
            new_total = (user_locked.balance_total or Decimal(0)) + amount_dollars
            new_deposits = (user_locked.total_deposits or Decimal(0)) + amount_dollars

            db.execute(
                text("""
                    UPDATE users 
                    SET balance_available = :ba, 
                        balance_total = :bt, 
                        total_deposits = :td, 
                        updated_at = NOW()
                    WHERE id = :uid
                """),
                {
                    "ba": new_available, 
                    "bt": new_total, 
                    "td": new_deposits, 
                    "uid": user_locked.id
                }
            )

            # E. PRIMER DEPÓSITO
            if not user_locked.first_deposit_made:
                db.execute(
                    text("""
                        UPDATE users 
                        SET first_deposit_made = TRUE, 
                            first_deposit_amount = :amt, 
                            first_deposit_date = NOW(),
                            status = 'ACTIVE' 
                        WHERE id = :uid
                    """),
                    {"amt": amount_dollars, "uid": user_locked.id}
                )

            db.commit()
            logger.info(
                f"✅ Saldo acreditado a usuario {user_locked.id} "
                f"(Telegram: {user_locked.telegram_id}). Nuevo total: ${new_total}"
            )

            # F. NOTIFICACIÓN
            try:
                send_telegram_notification(
                    int(user.telegram_id),
                    f"✅ <b>¡Recarga Exitosa!</b>\n\n"
                    f"💰 Monto: <b>${amount_dollars} USD</b>\n"
                    f"🏦 Saldo Disponible: ${new_available}\n"
                    f"💵 Saldo Total: ${new_total}\n\n"
                    f"¡Gracias por tu pago!"
                )
            except Exception as e:
                logger.error(f"⚠️ Error enviando notificación: {e}")

            return {"status": "success", "user_id": user_locked.id, "amount": float(amount_dollars)}

        except Exception as e:
            db.rollback()
            logger.error(f"❌ Error DB Stripe Webhook: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal Error")
