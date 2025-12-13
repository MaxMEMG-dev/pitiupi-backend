# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei (PRODUCCIÓN)
# PITIUPI v5.1 — STOKEN CORRECTO + VALIDACIONES COMPLETAS
# ============================================================

from fastapi import APIRouter, Request, HTTPException
from datetime import datetime   # ✅ IMPORT CRÍTICO (ANTES FALTABA)
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

# ============================================================
# VARIABLES DE ENTORNO
# ============================================================

APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Validación crítica en producción
if not APP_KEY:
    logger.critical("❌ NUVEI_APP_KEY_SERVER no configurado — abortando webhook")
    raise RuntimeError("NUVEI_APP_KEY_SERVER no configurado")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado — notificaciones Telegram desactivadas")

# ============================================================
# STOKEN — FÓRMULA OFICIAL NUVEI
# MD5(transaction_id_application_code_user_id_app_key)
# ============================================================

def generate_stoken(
    transaction_id: str,
    application_code: str,
    user_id: str,
    app_key: str
) -> str:
    """
    Genera STOKEN según documentación oficial Nuvei LinkToPay.
    IMPORTANTE:
    - application_code viene DEL WEBHOOK
    - user_id debe ser STRING
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    stoken = hashlib.md5(raw.encode()).hexdigest()

    logger.info("🔐 STOKEN DEBUG")
    logger.info(f"   RAW      : {transaction_id}_{application_code}_{user_id}_***")
    logger.info(f"   HASH MD5 : {stoken}")

    return stoken

# ============================================================
# ENVÍO DE MENSAJES TELEGRAM
# ============================================================

def send_telegram_message(chat_id: int, text: str):
    if not BOT_TOKEN:
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
            logger.error(f"❌ Telegram error: {resp.text}")

    except Exception:
        logger.error("❌ Error enviando mensaje Telegram", exc_info=True)

# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    """
    Webhook oficial Nuvei.
    Valida STOKEN, procesa el pago y actualiza balance.
    """
    try:
        payload = await request.json()
        logger.info("📥 [Nuvei] Webhook recibido")

        tx = payload.get("transaction")
        user = payload.get("user", {})

        if not tx:
            logger.warning("⚠️ Webhook sin transaction")
            return {"status": "OK"}

        # --------------------------------------------------
        # DATOS OFICIALES NUVEI
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
        telegram_id = user.get("id")  # STRING

        # Validación mínima
        if not all([transaction_id, intent_id, telegram_id, application_code]):
            logger.warning("⚠️ Webhook incompleto — ignorado")
            return {"status": "OK"}

        try:
            intent_id = int(intent_id)
        except ValueError:
            logger.error("❌ dev_reference no es numérico")
            return {"status": "OK"}

        # --------------------------------------------------
        # VALIDACIÓN STOKEN (CRÍTICA)
        # --------------------------------------------------
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
            app_key=APP_KEY,
        )

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido — webhook rechazado")
            raise HTTPException(status_code=203, detail="Token error")

        logger.info("✅ STOKEN válido")

        # --------------------------------------------------
        # OBTENER INTENT
        # --------------------------------------------------
        intent = get_payment_intent(intent_id)
        if not intent:
            logger.error(f"❌ Intent {intent_id} no existe")
            return {"status": "OK"}

        # --------------------------------------------------
        # IDEMPOTENCIA
        # --------------------------------------------------
        if intent.get("status") == "paid":
            logger.info(f"🔁 Intent {intent_id} ya procesado")
            return {"status": "OK"}

        # --------------------------------------------------
        # GUARDAR order_id SI NO EXISTE
        # --------------------------------------------------
        if order_id and not intent.get("order_id"):
            update_payment_intent(intent_id, order_id=order_id)

        # --------------------------------------------------
        # PAGO APROBADO
        # status = 1 | status_detail = 3
        # --------------------------------------------------
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 Pago aprobado → Intent {intent_id}")

            mark_intent_paid(
                intent_id=intent_id,
                provider_tx_id=transaction_id,
                status_detail=int(status_detail),
                authorization_code=authorization_code,
                message="Pago aprobado por Nuvei",
            )

            telegram_id_int = int(telegram_id)
            new_balance = add_user_balance(telegram_id_int, amount)

            voucher = (
                "🎉 <b>PAGO APROBADO</b>\n\n"
                f"💳 <b>Monto:</b> ${amount:.2f}\n"
                f"🧾 <b>Transacción:</b> {transaction_id}\n"
                f"🔐 <b>Autorización:</b> {authorization_code or 'N/A'}\n"
                f"📅 <b>Fecha:</b> {paid_date or 'N/A'}\n"
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
            logger.info(f"ℹ️ Estado no procesado: {status}/{status_detail}")

        return {"status": "OK"}

    except HTTPException:
        raise
    except Exception:
        logger.error("❌ Error crítico en webhook Nuvei", exc_info=True)
        return {"status": "OK"}

# ============================================================
# HEALTHCHECK
# ============================================================

@router.get("/health")
async def webhook_health():
    return {
        "status": "healthy",
        "service": "nuvei_webhook",
        "app_key_configured": bool(APP_KEY),
        "bot_token_configured": bool(BOT_TOKEN),
        "timestamp": datetime.now().isoformat(),
    }
