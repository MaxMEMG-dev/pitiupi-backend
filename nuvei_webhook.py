# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v5.1 — PRODUCCIÓN (STOKEN CORRECTO + BALANCE)
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

router = APIRouter(prefix="/nuvei", tags=["Nuvei"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO (CRÍTICAS)
# ============================================================

APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not APP_CODE or not APP_KEY:
    logger.error("❌ NUVEI_APP_CODE_SERVER o NUVEI_APP_KEY_SERVER NO configurados")


# ============================================================
# STOKEN — LINKTOPAY (OFICIAL)
# MD5(transaction_id + "_" + APP_CODE + "_" + user_id + "_" + APP_KEY)
# ============================================================

def generate_stoken(transaction_id: str, user_id: str) -> str:
    raw = f"{transaction_id}_{APP_CODE}_{user_id}_{APP_KEY}"
    stoken = hashlib.md5(raw.encode()).hexdigest()

    # Logs de auditoría (clave para debugging)
    logger.info("🔐 STOKEN DEBUG")
    logger.info(f"RAW      : {raw}")
    logger.info(f"EXPECTED : {stoken}")

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
            logger.error(f"❌ Error Telegram: {resp.text}")

    except Exception as e:
        logger.error("❌ Error enviando mensaje Telegram", exc_info=True)


# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info("📥 [Nuvei] Webhook recibido")

        tx = payload.get("transaction")
        user = payload.get("user", {})

        if not tx:
            logger.warning("⚠️ Webhook sin transaction")
            return {"status": "OK"}

        # --------------------------------------------------
        # CAMPOS OFICIALES NUVEI
        # --------------------------------------------------
        transaction_id = tx.get("id")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        intent_id = tx.get("dev_reference")
        order_id = tx.get("ltp_id")
        authorization_code = tx.get("authorization_code")
        paid_date = tx.get("paid_date")
        amount = float(tx.get("amount", 0))

        telegram_id = user.get("id")  # STRING según Nuvei

        if not transaction_id or not intent_id or not telegram_id:
            logger.warning("⚠️ Webhook incompleto — ignorado")
            return {"status": "OK"}

        intent_id = int(intent_id)
        telegram_id_int = int(telegram_id)

        # --------------------------------------------------
        # VALIDAR STOKEN (CRÍTICO)
        # --------------------------------------------------
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            user_id=str(telegram_id),
        )

        logger.info(f"STOKEN RECIBIDO : {sent_stoken}")

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido — webhook rechazado")
            return {"status": "token error"}, 203

        logger.info("✅ STOKEN válido — webhook auténtico")

        # --------------------------------------------------
        # OBTENER INTENT
        # --------------------------------------------------
        intent = get_payment_intent(intent_id)
        if not intent:
            logger.error(f"❌ Intent {intent_id} no existe")
            return {"status": "OK"}

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
            return {"status": "OK"}

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

        return {"status": "OK"}

    except Exception:
        logger.error("❌ Error crítico en webhook Nuvei", exc_info=True)
        return {"status": "OK"}
