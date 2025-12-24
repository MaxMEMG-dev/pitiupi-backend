# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.8 — FIX: NameError PaymentIntentStatus
# ============================================================

from fastapi import APIRouter, Request, HTTPException
import hashlib
import logging
import os
import requests
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional

router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

# --- INTENTO DE IMPORTACIÓN SEGURO ---
HAS_DB = False
try:
    from database.session import get_session
    from database.services import payments_service
    from database.models.payment_intents import PaymentIntentStatus
    HAS_DB = True
except ImportError:
    # Si no hay base de datos, creamos una clase vacía para que el código no explote
    class PaymentIntentStatus:
        COMPLETED = "completed"
    logger.warning("⚠️ No se pudieron importar módulos de DB: Funcionando en modo Proxy")

# Variables de entorno
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# --- HELPERS ---

def generate_stoken(transaction_id: str, application_code: str, user_id: str, app_key: str) -> str:
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()

def send_telegram_notification(chat_id: int, text: str):
    if not BOT_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except: pass

# --- WEBHOOK ---

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        tx = payload.get("transaction", {})
        
        transaction_id = tx.get("id")
        dev_reference = tx.get("dev_reference") 
        app_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount = Decimal(str(tx.get("amount", "0")))
        sent_stoken = tx.get("stoken")

        # Extraer Telegram ID de la referencia (Formato: PITIUPI-ID-...)
        # Si tu referencia es distinta, ajusta este split
        try:
            telegram_id = dev_reference.split("-")[1]
        except:
            telegram_id = "0"

        # 1. Validar Firma
        expected = generate_stoken(transaction_id, app_code, telegram_id, APP_KEY)
        if sent_stoken != expected:
            logger.error(f"❌ Firma inválida")
            return {"status": "OK"}

        # 2. Procesar Pago Aprobado
        if status == "1" and status_detail == "3":
            logger.info(f"💰 Pago Aprobado: {amount} USD")

            if HAS_DB:
                # Caso Render (DB Local)
                db = get_session()
                try:
                    payments_service.confirm_payment_intent_service(
                        intent_uuid=dev_reference,
                        provider_tx_id=transaction_id,
                        amount_received=float(amount),
                        session=db
                    )
                    db.commit()
                finally:
                    db.close()
            elif BOT_BACKEND_URL:
                # Caso Local (Delegar al Bot)
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

            send_telegram_notification(int(telegram_id), f"✅ <b>¡Pago Recibido!</b>\nHas recargado ${amount} USD.")

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"status": "OK"}

@router.get("/health")
async def health():
    return {"status": "ok", "db": HAS_DB}
