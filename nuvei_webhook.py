from fastapi import APIRouter, Request
import hashlib
import logging
import os
import requests

from payments_core import (
    mark_intent_paid,
    update_payment_intent,
    get_payment_intent,
    add_user_balance      # 🔥 Importante
)

router = APIRouter()
logger = logging.getLogger(__name__)

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")


def generate_stoken(transaction_id: str, user_id: str) -> str:
    raw = f"{transaction_id}_{APP_CODE}_{user_id}_{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            logger.error(f"❌ Telegram error: {r.text}")
        else:
            logger.info(f"📩 Mensaje enviado a TelegramID={chat_id}")
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")


@router.post("/nuvei/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info(f"[Nuvei] Webhook recibido: {payload}")

        if "transaction" not in payload:
            logger.error("❌ Webhook inválido")
            return {"status": "OK"}

        tx = payload["transaction"]
        user_data = payload.get("user", {})

        transaction_id = tx.get("id")
        status = tx.get("status")
        status_detail = tx.get("status_detail")
        intent_id = tx.get("dev_reference")
        authorization_code = tx.get("authorization_code")
        paid_date = tx.get("paid_date")
        amount = float(tx.get("amount"))
        user_id = int(user_data.get("id"))  # Telegram ID

        if not intent_id:
            return {"status": "OK"}

        intent_id = int(intent_id)

        # -----------------------------
        # VALIDAR STOKEN
        # -----------------------------
        sent_stoken = tx.get("stoken")
        expected = generate_stoken(transaction_id, str(user_id))

        if sent_stoken != expected:
            logger.error("❌ STOKEN inválido")
            return {"status": "OK"}

        # -----------------------------
        # GUARDAR order_id
        # -----------------------------
        existing = get_payment_intent(intent_id)
        if existing and not existing["order_id"]:
            update_payment_intent(intent_id, order_id=tx.get("ltp_id"))

        # -----------------------------
        # SI EL PAGO FUE APROBADO
        # -----------------------------
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 Pago aprobado para intent {intent_id}")

            # 1) Marcar como pagado
            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=status_detail,
                authorization_code=authorization_code
            )

            # 2) Actualizar saldo
            new_balance = add_user_balance(user_id, amount)

            # 3) Enviar voucher Telegram
            voucher = (
                "🎉 <b>PAGO APROBADO</b>\n\n"
                f"💳 <b>Monto:</b> ${amount}\n"
                f"🧾 <b>Transacción:</b> {transaction_id}\n"
                f"🔐 <b>Autorización:</b> {authorization_code}\n"
                f"📅 <b>Fecha:</b> {paid_date}\n"
                f"🏷 <b>Referencia interna:</b> {intent_id}\n\n"
                f"💰 <b>Nuevo saldo:</b> ${new_balance}\n\n"
                "Gracias por usar PITIUPI 🚀"
            )

            send_telegram_message(user_id, voucher)

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"[Nuvei Callback ERROR] {e}", exc_info=True)
        return {"status": "OK"}
