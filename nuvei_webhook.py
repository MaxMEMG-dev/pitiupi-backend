# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v5.1 — PRODUCCIÓN
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

APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")


# ============================================================
# STOKEN (según documentación oficial Nuvei)
# ============================================================

def generate_stoken(
    transaction_id: str,
    application_code: str,
    user_id: str,
) -> str:
    """
    MD5(transaction_id_application_code_user_id_app_key)
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


# ============================================================
# Enviar mensaje Telegram
# ============================================================

def send_telegram_message(chat_id: int, text: str):
    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN no configurado")
        return

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10
        )

        if resp.status_code != 200:
            logger.error(f"❌ Telegram error: {resp.text}")

    except Exception as e:
        logger.error(f"❌ Error enviando Telegram: {e}")


# ============================================================
# Webhook Nuvei
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info(f"📥 [Nuvei] Webhook recibido")

        tx = payload.get("transaction")
        user = payload.get("user", {})

        if not tx or "id" not in tx:
            return {"status": "OK"}

        # --------------------------------------------------
        # Extraer campos oficiales
        # --------------------------------------------------
        transaction_id = tx.get("id")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        intent_id = tx.get("dev_reference")
        application_code = tx.get("application_code")
        order_id = tx.get("ltp_id")
        authorization_code = tx.get("authorization_code")
        paid_date = tx.get("paid_date")
        amount = float(tx.get("amount", 0))

        telegram_id = user.get("id")

        if not intent_id or not telegram_id:
            return {"status": "OK"}

        intent_id = int(intent_id)
        telegram_id = int(telegram_id)

        # --------------------------------------------------
        # Validar STOKEN (CRÍTICO)
        # --------------------------------------------------
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
        )

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido")
            return {"status": "OK"}

        # --------------------------------------------------
        # Obtener intent
        # --------------------------------------------------
        intent = get_payment_intent(intent_id)
        if not intent:
            return {"status": "OK"}

        # --------------------------------------------------
        # Guardar order_id si no existe
        # --------------------------------------------------
        if order_id and not intent.get("order_id"):
            update_payment_intent(intent_id, order_id=order_id)

        # --------------------------------------------------
        # Idempotencia
        # --------------------------------------------------
        if intent.get("status") == "paid":
            return {"status": "OK"}

        # --------------------------------------------------
        # APROBADO → SUMAR BALANCE
        # --------------------------------------------------
        if status == "1" and status_detail == "3":
            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=int(status_detail),
                authorization_code=authorization_code,
                message="Pago aprobado por Nuvei",
            )

            new_balance = add_user_balance(telegram_id, amount)

            voucher = (
                "🎉 <b>PAGO APROBADO</b>\n\n"
                f"💳 <b>Monto:</b> ${amount:.2f}\n"
                f"🧾 <b>Transacción:</b> {transaction_id}\n"
                f"🔐 <b>Autorización:</b> {authorization_code}\n"
                f"📅 <b>Fecha:</b> {paid_date}\n"
                f"🏷 <b>Referencia:</b> {intent_id}\n\n"
                f"💰 <b>Nuevo saldo:</b> ${new_balance:.2f}\n\n"
                "Gracias por usar <b>PITIUPI</b> 🚀"
            )

            send_telegram_message(telegram_id, voucher)

        # --------------------------------------------------
        # CANCELADO
        # --------------------------------------------------
        elif status == "2":
            update_payment_intent(intent_id, status="cancelled")

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"[Nuvei Callback ERROR] {e}", exc_info=True)
        return {"status": "OK"}
