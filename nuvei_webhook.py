from fastapi import APIRouter, Request, HTTPException
import hashlib
import logging
import os
import requests

from payments_core import (
    mark_intent_paid,
    update_payment_intent,
    get_payment_intent
)

router = APIRouter()
logger = logging.getLogger(__name__)

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")  # 🔥 Necesario para enviar a Telegram


def generate_stoken(transaction_id: str, user_id: str) -> str:
    raw = f"{transaction_id}_{APP_CODE}_{user_id}_{APP_KEY}"
    return hashlib.md5(raw.encode()).hexdigest()


def send_telegram_voucher(chat_id: int, text: str):
    """Envía un mensaje directo al usuario en Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"❌ Error enviando mensaje Telegram: {resp.text}")
        else:
            logger.info(f"📩 Voucher enviado a TelegramID={chat_id}")
    except Exception as e:
        logger.error(f"❌ Error Telegram API: {e}")


@router.post("/nuvei/callback")
async def nuvei_callback(request: Request):
    """
    Webhook oficial de Nuvei LinkToPay.
    Recibe los datos reales del pago, valida el stoken y actualiza la DB.
    Además ENVÍA EL VOUCHER AL USUARIO EN TELEGRAM.
    """
    try:
        payload = await request.json()
        logger.info(f"[Nuvei] Webhook recibido: {payload}")

        if "transaction" not in payload:
            logger.error("❌ Webhook inválido: falta 'transaction'")
            return {"status": "OK"}

        transaction = payload["transaction"]
        user_data = payload.get("user", {})

        # -------------------------------
        # DATOS IMPORTANTES
        # -------------------------------
        transaction_id = transaction.get("id")
        status = transaction.get("status")               # "1" = success
        status_detail = transaction.get("status_detail") # "3" = approved
        dev_reference = transaction.get("dev_reference") # Nuestro intent_id
        authorization_code = transaction.get("authorization_code")
        paid_date = transaction.get("paid_date")
        amount = transaction.get("amount")

        user_id = user_data.get("id")  # Telegram ID real

        if not dev_reference:
            logger.error("❌ Webhook sin dev_reference")
            return {"status": "OK"}

        intent_id = int(dev_reference)

        # -------------------------------
        # VALIDAR STOKEN
        # -------------------------------
        sent_stoken = transaction.get("stoken")
        correct_stoken = generate_stoken(transaction_id, user_id)

        if sent_stoken != correct_stoken:
            logger.error("❌ ERROR: STOKEN inválido, webhook rechazado")
            return {"status": "OK"}  # No enviar error → Nuvei reintenta

        # -------------------------------
        # GUARDAR order_id
        # -------------------------------
        existing = get_payment_intent(intent_id)
        if existing and not existing["order_id"]:
            ltp_id = transaction.get("ltp_id")
            if ltp_id:
                update_payment_intent(intent_id, order_id=ltp_id)

        # -------------------------------
        # VALIDAR APROBACIÓN
        # -------------------------------
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 Pago APROBADO para intent {intent_id}")

            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=status_detail,
                authorization_code=authorization_code
            )

            # -------------------------------
            # 🔥 ENVIAR VOUCHER A TELEGRAM
            # -------------------------------
            voucher = (
                "🎉 <b>PAGO APROBADO</b>\n\n"
                "Tu depósito ha sido acreditado correctamente.\n\n"
                f"<b>Monto:</b> ${amount}\n"
                f"<b>Transacción:</b> {transaction_id}\n"
                f"<b>Autorización:</b> {authorization_code}\n"
                f"<b>Fecha:</b> {paid_date}\n"
                f"<b>Referencia interna:</b> {intent_id}\n\n"
                "Gracias por usar PITIUPI 🚀"
            )

            send_telegram_voucher(int(user_id), voucher)

        else:
            logger.warning(f"🔶 Pago no aprobado: status={status}, detail={status_detail}")

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"[Nuvei Callback ERROR] {str(e)}", exc_info=True)
        return {"status": "OK"}  # Nunca enviar error a Nuvei
