# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v5.1 — ACTUALIZA BALANCE + NOTIFICA BOT
# ============================================================

from fastapi import APIRouter, Request
import hashlib
import logging
import os
import requests

from payments_core import (
    mark_intent_paid,
    update_payment_intent,
    get_payment_intent,
    add_user_balance,
)
router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")


# ============================================================
# STOKEN (validación Nuvei)
# ============================================================

def generate_stoken(transaction_id: str, user_id: str) -> str:
    raw = f"{transaction_id}_{APP_CODE}_{user_id}_{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


# ============================================================
# Envío de mensaje Telegram
# ============================================================

def send_telegram_message(chat_id: int, text: str):
    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN no configurado")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"❌ Telegram API error: {resp.text}")
        else:
            logger.info(f"📩 Mensaje enviado a TelegramID={chat_id}")
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")


# ============================================================
# Webhook Nuvei
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info(f"📥 [Nuvei] Webhook recibido: {payload}")

        # -----------------------------
        # Validación básica
        # -----------------------------
        tx = payload.get("transaction")
        user_data = payload.get("user", {})

        if not tx:
            logger.warning("⚠️ Webhook sin transaction")
            return {"status": "OK"}

        transaction_id = tx.get("id")
        status = tx.get("status")
        status_detail = tx.get("status_detail")
        intent_id = tx.get("dev_reference")
        authorization_code = tx.get("authorization_code")
        paid_date = tx.get("paid_date")
        amount = float(tx.get("amount", 0))
        order_id = tx.get("ltp_id")

        telegram_id = user_data.get("id")  # Telegram ID (string o int)

        if not intent_id or not telegram_id:
            logger.warning("⚠️ Webhook sin intent_id o telegram_id")
            return {"status": "OK"}

        intent_id = int(intent_id)
        telegram_id = int(telegram_id)

        # -----------------------------
        # VALIDAR STOKEN
        # -----------------------------
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(transaction_id, str(telegram_id))

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido — posible fraude")
            return {"status": "OK"}

        # -----------------------------
        # Obtener intent actual
        # -----------------------------
        intent = get_payment_intent(intent_id)
        if not intent:
            logger.error(f"❌ Intent {intent_id} no existe")
            return {"status": "OK"}

        # -----------------------------
        # Guardar order_id si aún no existe
        # -----------------------------
        if order_id and not intent.get("order_id"):
            update_payment_intent(intent_id, order_id=order_id)

        # -----------------------------
        # Idempotencia: si ya está pagado
        # -----------------------------
        if intent.get("status") == "paid":
            logger.info(f"🔁 Intent {intent_id} ya estaba pagado — ignorado")
            return {"status": "OK"}

        # -----------------------------
        # Pago aprobado (Nuvei)
        # status == "1" AND status_detail == "3"
        # -----------------------------
        if status == "1" and str(status_detail) == "3":
            logger.info(f"🟢 Pago aprobado → Intent {intent_id}")

            # 1️⃣ Marcar intent como pagado
            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=status_detail,
                authorization_code=authorization_code,
                message="Pago aprobado por Nuvei"
            )

            # 2️⃣ Actualizar balance del usuario
            new_balance = add_user_balance(telegram_id, amount)

            # 3️⃣ Enviar voucher por Telegram
            voucher = (
                "🎉 <b>PAGO APROBADO</b>\n\n"
                f"💳 <b>Monto:</b> ${amount:.2f}\n"
                f"🧾 <b>Transacción:</b> {transaction_id}\n"
                f"🔐 <b>Autorización:</b> {authorization_code}\n"
                f"📅 <b>Fecha:</b> {paid_date}\n"
                f"🏷 <b>Referencia interna:</b> {intent_id}\n\n"
                f"💰 <b>Nuevo saldo:</b> ${new_balance:.2f}\n\n"
                "Gracias por usar <b>PITIUPI</b> 🚀"
            )

            send_telegram_message(telegram_id, voucher)

        else:
            logger.info(
                f"ℹ️ Webhook ignorado — status={status} detail={status_detail}"
            )

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"[Nuvei Callback ERROR] {e}", exc_info=True)
        return {"status": "OK"}

