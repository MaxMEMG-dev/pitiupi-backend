# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v5.1 — PRODUCCIÓN
# STOKEN CORRECTO + UPDATE BALANCE
# ============================================================

from fastapi import APIRouter, Request, Response
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

router = APIRouter(prefix="/nuvei", tags=["Nuvei"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO (CRÍTICAS)
# ============================================================

APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not APP_KEY:
    logger.critical("❌ NUVEI_APP_KEY_SERVER NO configurado")


# ============================================================
# STOKEN — SEGÚN DOCUMENTACIÓN OFICIAL NUVEI
# MD5(transaction_id_application_code_user_id_app_key)
# ⚠️ application_code VIENE DEL WEBHOOK, NO DEL ENV
# ============================================================

def generate_stoken(
    transaction_id: str,
    application_code: str,
    user_id: str,
) -> str:
    raw = f"{transaction_id}_{application_code}_{user_id}_{APP_KEY}"
    stoken = hashlib.md5(raw.encode()).hexdigest()

    # 🔍 LOGS DE AUDITORÍA (OBLIGATORIOS)
    logger.info("🔐 STOKEN DEBUG")
    logger.info(f"RAW STRING        : {raw}")
    logger.info(f"STOKEN CALCULADO  : {stoken}")

    return stoken


# ============================================================
# ENVÍO DE MENSAJE A TELEGRAM
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
            timeout=10,
        )

        if resp.status_code != 200:
            logger.error(f"❌ Error Telegram API: {resp.text}")

    except Exception:
        logger.error("❌ Error enviando mensaje Telegram", exc_info=True)


# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info("📥 [Nuvei] Webhook recibido")
        logger.debug(payload)

        tx = payload.get("transaction")
        user = payload.get("user", {})

        if not tx:
            logger.warning("⚠️ Webhook sin transaction")
            return Response(status_code=200)

        # --------------------------------------------------
        # CAMPOS OFICIALES NUVEI
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

        telegram_id = user.get("id")  # ⚠️ STRING

        logger.info(
            f"📋 TX={transaction_id} | APP={application_code} | USER={telegram_id} | INTENT={intent_id}"
        )

        if not all([transaction_id, application_code, intent_id, telegram_id]):
            logger.warning("⚠️ Webhook incompleto — ignorado")
            return Response(status_code=200)

        intent_id = int(intent_id)
        telegram_id_int = int(telegram_id)

        # --------------------------------------------------
        # VALIDACIÓN STOKEN (CRÍTICA)
        # --------------------------------------------------
        sent_stoken = tx.get("stoken")

        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),  # ⚠️ STRING
        )

        logger.info(f"STOKEN RECIBIDO   : {sent_stoken}")
        logger.info(f"STOKEN ESPERADO   : {expected_stoken}")

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido — webhook rechazado")
            # ⚠️ 203 = token error → Nuvei REINTENTA
            return Response(status_code=203)

        logger.info("✅ STOKEN válido — webhook auténtico")

        # --------------------------------------------------
        # OBTENER INTENT
        # --------------------------------------------------
        intent = get_payment_intent(intent_id)
        if not intent:
            logger.error(f"❌ Intent {intent_id} no existe")
            return Response(status_code=200)

        # --------------------------------------------------
        # GUARDAR order_id SI NO EXISTE
        # --------------------------------------------------
        if order_id and not intent.get("order_id"):
            update_payment_intent(intent_id, order_id=order_id)

        # --------------------------------------------------
        # IDEMPOTENCIA
        # --------------------------------------------------
        if intent.get("status") == "paid":
            logger.info(f"🔁 Intent {intent_id} ya procesado")
            return Response(status_code=200)

        # --------------------------------------------------
        # PAGO APROBADO
        # status = 1 | status_detail = 3
        # --------------------------------------------------
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 Pago aprobado → Intent {intent_id}")

            # 1️⃣ Marcar intent como pagado
            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=int(status_detail),
                authorization_code=authorization_code,
                message="Pago aprobado por Nuvei",
            )

            # 2️⃣ Actualizar balance
            new_balance = add_user_balance(telegram_id_int, amount)

            # 3️⃣ Enviar voucher Telegram
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

            send_telegram_message(telegram_id_int, voucher)

        # --------------------------------------------------
        # PAGO CANCELADO
        # --------------------------------------------------
        elif status == "2":
            update_payment_intent(intent_id, status="cancelled")
            logger.info(f"⚠️ Pago cancelado → Intent {intent_id}")

        else:
            logger.info(
                f"ℹ️ Webhook ignorado → status={status} detail={status_detail}"
            )

        return Response(status_code=200)

    except Exception:
        logger.critical("❌ ERROR CRÍTICO EN WEBHOOK NUVEI", exc_info=True)
        return Response(status_code=200)
