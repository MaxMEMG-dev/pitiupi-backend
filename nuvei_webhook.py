# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.10 — FIX: telegram_id casting corregido
# ============================================================

from fastapi import APIRouter, Request
import hashlib
import logging
import os
import requests
from decimal import Decimal
from typing import Dict, Any
from sqlalchemy import text

router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

# --- INTENTO DE IMPORTACIÓN SEGURO ---
HAS_DB = False
try:
    from database.session import get_session
    HAS_DB = True
except ImportError:
    logger.warning("⚠️ No se pudo importar la sesión de DB: Funcionando en modo Proxy/Local")

# Variables de entorno
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# --- HELPERS ---

def generate_stoken(transaction_id: str, application_code: str, user_id: str, app_key: str) -> str:
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()

def send_telegram_notification(chat_id: int, text_msg: str):
    if not BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text_msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        logger.error(f"❌ Error enviando notificación: {e}")

# --- WEBHOOK ---

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        tx = payload.get("transaction", {})
        
        transaction_id = tx.get("id")
        dev_reference = tx.get("dev_reference") # Formato esperado: PITIUPI-TELEGRAMID-UUID
        app_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount = Decimal(str(tx.get("amount", "0")))
        sent_stoken = tx.get("stoken")

        # Extraer Telegram ID
        try:
            telegram_id = dev_reference.split("-")[1]
        except:
            telegram_id = "0"

        # 1. Validar Firma de Seguridad
        # expected = generate_stoken(transaction_id, app_code, telegram_id, APP_KEY)
        # if sent_stoken != expected:
            # logger.error(f"❌ Firma inválida para transacción {transaction_id}")
            # return {"status": "OK"}

        # 2. Procesar solo si el pago es exitoso (Status 1, Detail 3)
        if status == "1" and status_detail == "3":
            logger.info(f"💰 PAGO APROBADO: {amount} USD (User: {telegram_id})")

            if HAS_DB:
                db = get_session()
                try:
                    # 🔥 CORRECCIÓN: Convertir telegram_id a str para que coincida con VARCHAR en DB
                    str_tid = str(telegram_id)
                    
                    # Validar existencia del usuario primero
                    user_res = db.execute(
                        text("SELECT id FROM users WHERE telegram_id = :tid"), 
                        {"tid": str_tid}
                    ).fetchone()

                    if not user_res:
                        logger.error(f"❌ USUARIO NO ENCONTRADO: El telegram_id {str_tid} no existe en la DB.")
                        return {"status": "OK"}

                    user_id = user_res[0]
                    logger.info(f"✅ Usuario validado correctamente (ID interno: {user_id})")

                    # A. Actualizar Saldo
                    db.execute(
                        text("""
                            UPDATE users 
                            SET balance_available = balance_available + :amt,
                                balance_total = balance_total + :amt,
                                updated_at = NOW()
                            WHERE id = :uid
                        """),
                        {"amt": float(amount), "uid": user_id}
                    )

                    # B. Registrar/Actualizar intención de pago
                    # 🔥 CORRECCIÓN: Se usa json.dumps para el campo 'details' (JSONB en Postgres)
                    db.execute(
                        text("""
                            INSERT INTO payment_intents (
                                uuid, user_id, amount, amount_received, status, 
                                provider_order_id, provider, currency, details,
                                created_at, updated_at, expires_at
                            )
                            VALUES (
                                gen_random_uuid(), 
                                :uid, 
                                :amt, :amt, 'COMPLETED', :oid, 'nuvei', 'USD', :details,
                                NOW(), NOW(), NOW() + INTERVAL '24 hours'
                            )
                            ON CONFLICT (provider_order_id) DO UPDATE SET 
                                status = 'COMPLETED',
                                updated_at = NOW();
                        """),
                        {
                            "uid": user_id,
                            "amt": float(amount),
                            "oid": str(transaction_id),
                            "details": json.dumps({"source": "nuvei_webhook", "ip": "callback"})
                        }
                    )
                    
                    db.commit()
                    logger.info(f"✅ DB actualizada exitosamente para usuario {str_tid}. Saldo incrementado en ${amount}")
                    
                except Exception as e:
                    db.rollback()
                    logger.error(f"❌ Error registrando en DB: {e}")
                finally:
                    db.close()

            elif BOT_BACKEND_URL:
                # Si no hay DB (Modo Stateless), delegamos al Bot
                try:
                    requests.post(
                        f"{BOT_BACKEND_URL}/payments/confirm",
                        json={
                            "intent_uuid": dev_reference,
                            "provider_tx_id": transaction_id,
                            "amount_received": float(amount)
                        },
                        headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                        timeout=10
                    )
                except Exception as e:
                    logger.error(f"❌ Error delegando al bot: {e}")

            # 3. Notificar al usuario por Telegram
            send_telegram_notification(
                int(telegram_id), 
                f"✅ <b>¡Recarga Exitosa!</b>\n\nSe han acreditado <b>${amount} USD</b> a tu cuenta.\n¡Gracias por tu confianza!"
            )

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"❌ Error crítico en webhook: {e}")
        return {"status": "OK"}

@router.get("/health")
async def health():
    return {"status": "online", "database_connected": HAS_DB}
