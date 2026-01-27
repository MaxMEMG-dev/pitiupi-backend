# ============================================================
# stripe_webhook.py — Receptor de Webhooks Stripe
# PITIUPI v6.4 — Adaptación de lógica Nuvei a Stripe
# ============================================================

import stripe
from fastapi import APIRouter, Request, HTTPException, Header
import logging
import os
import json
import requests
from decimal import Decimal
from typing import Dict, Any

# Intentos de importación de DB (Misma lógica robusta que tenías)
HAS_DB = False
try:
    from database.session import db_session
    from database.models.user import User
    from sqlalchemy import select, text
    HAS_DB = True
except ImportError as e:
    # Logger configurado más abajo
    pass

router = APIRouter(tags=["Stripe"])
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stripe-webhook")

# Variables de entorno
STRIPE_API_KEY = os.getenv("STRIPE_SECRET_KEY") # sk_test_...
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET") # whsec_...
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

stripe.api_key = STRIPE_API_KEY

# --- HELPERS (Reutilizados de tu lógica) ---

def send_telegram_notification(chat_id: int, text_msg: str):
    """Envía notificación al usuario vía Telegram (Sin bloquear DB)."""
    if not BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text_msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        logger.error(f"❌ Error notificación Telegram: {e}")

# --- WEBHOOK ---

@router.post("/callback")
async def stripe_callback(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    """
    Procesa eventos 'checkout.session.completed' de Stripe.
    Mantiene la misma robustez (Idempotencia + AML) que el webhook de Nuvei.
    """
    payload = await request.body()
    event = None

    # 1. VERIFICACIÓN DE FIRMA (Reemplaza a stoken)
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.error("❌ Firma Stripe inválida")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. FILTRADO DE EVENTOS
    if event['type'] != 'checkout.session.completed':
        # Respondemos 200 a otros eventos para que Stripe no reintente
        return {"status": "ignored", "type": event['type']}

    session = event['data']['object']
    
    # 3. EXTRACCIÓN DE DATOS
    transaction_id = session.get('id')          # cs_test_...
    payment_intent_id = session.get('payment_intent') # pi_...
    amount_cents = session.get('amount_total', 0)
    amount_dollars = Decimal(amount_cents) / 100
    currency = session.get('currency', 'usd').upper()
    
    # Metadata crítica que enviamos desde el Plugin de WP o payments_api
    metadata = session.get('metadata', {})
    user_id_param = metadata.get('user_id') or session.get('client_reference_id')
    
    # Referencia interna para logs
    dev_reference = f"STRIPE-{user_id_param}-{transaction_id[-8:]}"

    logger.info(f"📥 Stripe Payment: {transaction_id} | User: {user_id_param} | Amount: ${amount_dollars}")

    if not user_id_param:
        logger.error("❌ Webhook recibido sin User ID")
        return {"status": "error", "message": "missing_user_metadata"}

    # 4. PROCESAMIENTO EN BASE DE DATOS (Lógica Core de PITIUPI)
    if HAS_DB:
        with db_session() as db:
            try:
                # A. IDEMPOTENCIA (Verificar si ya existe por ID de Stripe)
                # Usamos el transaction_id (cs_...) como provider_order_id
                existing_intent = db.execute(
                    text("""
                        SELECT id, status FROM payment_intents 
                        WHERE provider_order_id = :order_id 
                        FOR UPDATE
                    """),
                    {"order_id": transaction_id}
                ).fetchone()

                if existing_intent:
                    if existing_intent.status == 'COMPLETED':
                        logger.info(f"✅ Pago ya procesado (Idempotencia): {transaction_id}")
                        return {"status": "OK", "message": "already_processed"}
                    
                    # Si existe pero estaba PENDING, lo actualizamos
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
                        {"amount": amount_dollars, "order_id": transaction_id, "payload": json.dumps(event)}
                    )
                    # Nota: Aquí deberíamos actualizar saldo si no se hizo antes, 
                    # pero asumimos flujo normal de inserción abajo si no existe.
                    # Para simplificar, si ya existe PENDING, asumimos que falta acreditar.
                    # (Continuamos al paso de User Balance Update)

                # B. BUSCAR Y BLOQUEAR USUARIO (AML Logic)
                # Buscamos por ID numérico (si viene de WP plugin) o telegram_id
                # Asumimos que user_id_param puede ser telegram_id o internal id.
                # Intentamos buscar por telegram_id primero como en Nuvei.
                user = db.query(User).filter(User.telegram_id == str(user_id_param)).first()
                if not user:
                    # Intento por ID interno si falla telegram_id
                    try:
                        user = db.query(User).filter(User.id == int(user_id_param)).first()
                    except:
                        pass
                
                if not user:
                    logger.error(f"❌ Usuario no encontrado: {user_id_param}")
                    raise HTTPException(status_code=404, detail="User not found")

                # Bloqueo de fila para evitar race conditions
                stmt = select(User).where(User.id == user.id).with_for_update()
                user_locked = db.execute(stmt).scalar_one()

                # C. INSERTAR PAYMENT INTENT (Si no existía)
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

                # D. ACTUALIZAR SALDOS (AML: Depósitos van a 'recharge' y 'total')
                new_recharge = (user_locked.balance_recharge or Decimal(0)) + amount_dollars
                new_total = (user_locked.balance_total or Decimal(0)) + amount_dollars
                new_deposits = (user_locked.total_deposits or Decimal(0)) + amount_dollars

                db.execute(
                    text("""
                        UPDATE users 
                        SET balance_recharge = :br, balance_total = :bt, 
                            total_deposits = :td, updated_at = NOW()
                        WHERE id = :uid
                    """),
                    {"br": new_recharge, "bt": new_total, "td": new_deposits, "uid": user_locked.id}
                )

                # E. PRIMER DEPÓSITO
                if not user_locked.first_deposit_made:
                    db.execute(
                        text("""
                            UPDATE users SET first_deposit_made = TRUE, 
                            first_deposit_amount = :amt, first_deposit_date = NOW(),
                            status = 'ACTIVE' WHERE id = :uid
                        """),
                        {"amt": amount_dollars, "uid": user_locked.id}
                    )

                db.commit()
                logger.info(f"✅ Saldo acreditado a usuario {user_locked.id}. Nuevo total: ${new_total}")

                # F. NOTIFICACIÓN
                try:
                    send_telegram_notification(
                        int(user.telegram_id), # Asegurarse de tener el telegram_id
                        f"✅ <b>¡Recarga Exitosa con Stripe!</b>\n\n"
                        f"💰 Monto: <b>${amount_dollars} USD</b>\n"
                        f"🏦 Saldo Total: ${new_total}\n"
                    )
                except:
                    pass

                return {"status": "success"}

            except Exception as e:
                db.rollback()
                logger.error(f"❌ Error DB Stripe Webhook: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Internal Error")

    else:
        # Modo Stateless (sin DB local, enviar a Bot Backend si existe)
        logger.warning("⚠️ Modo Stateless no implementado completamente para Stripe")
        return {"status": "ok", "mode": "stateless_ignored"}


