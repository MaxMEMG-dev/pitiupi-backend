# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v6.0 — Backend Nuvei (delegación a bot backend)
# ============================================================

from fastapi import APIRouter, Request, HTTPException
import hashlib
import logging
import os
import requests
from datetime import datetime
from decimal import Decimal

router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO
# ============================================================
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")  # https://pitiupi-bot.onrender.com
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

if not APP_KEY:
    raise RuntimeError("❌ NUVEI_APP_KEY_SERVER es obligatorio")

if not BOT_BACKEND_URL:
    raise RuntimeError("❌ BOT_BACKEND_URL es obligatorio")

if not INTERNAL_API_KEY:
    raise RuntimeError("❌ INTERNAL_API_KEY es obligatorio")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones desactivadas")

# ============================================================
# HELPERS INTERNOS
# ============================================================

def _internal_headers() -> dict:
    return {
        "X-Internal-API-Key": INTERNAL_API_KEY,
        "Content-Type": "application/json",
    }

# ============================================================
# STOKEN — FÓRMULA OFICIAL NUVEI
# ============================================================

def generate_stoken(
    transaction_id: str,
    application_code: str,
    user_id: str,
    app_key: str
) -> str:
    """
    Formula Nuvei:
    MD5(transaction_id_application_code_user_id_app_key)
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()

# ============================================================
# TELEGRAM (OPCIONAL)
# ============================================================

def send_telegram_message(chat_id: int, text: str) -> None:
    if not BOT_TOKEN:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception as e:
        logger.error(f"❌ Error enviando Telegram: {e}")

# ============================================================
# BOT BACKEND CALLS
# ============================================================

def get_telegram_id_from_intent(intent_uuid: str) -> int | None:
    url = f"{BOT_BACKEND_URL}/internal/payments/intent/{intent_uuid}"

    try:
        resp = requests.get(
            url,
            headers=_internal_headers(),
            timeout=10,
        )

        if resp.status_code == 200:
            return resp.json().get("telegram_id")

        logger.error(f"❌ Error intent lookup: {resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"❌ Error obteniendo telegram_id: {e}")
        return None


def call_bot_backend_confirm_payment(
    intent_uuid: str,
    transaction_id: str,
    amount: Decimal,
    authorization_code: str | None = None
) -> dict:
    url = f"{BOT_BACKEND_URL}/internal/payments/confirm"

    payload = {
        "intent_uuid": intent_uuid,
        "provider_tx_id": transaction_id,
        "amount_received": float(amount),
        "authorization_code": authorization_code,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=30,
        )

        if resp.status_code == 200:
            return {"success": True}

        if resp.status_code == 409:
            # Idempotencia: ya confirmado
            return {"success": True, "already_confirmed": True}

        logger.error(f"❌ Bot backend error {resp.status_code}: {resp.text[:200]}")
        return {"success": False}

    except Exception as e:
        logger.error(f"❌ Error confirmando pago en bot: {e}", exc_info=True)
        return {"success": False}

# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        payload = await request.json()
        logger.info(f"📥 Webhook Nuvei recibido")

        tx = payload.get("transaction")
        if not tx:
            return {"status": "OK"}

        transaction_id = tx.get("id")
        dev_reference = tx.get("dev_reference")
        application_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount_raw = tx.get("amount")
        sent_stoken = tx.get("stoken")
        authorization_code = tx.get("authorization_code")

        if not all([transaction_id, dev_reference, application_code, amount_raw]):
            return {"status": "OK"}

        amount = Decimal(str(amount_raw))

        telegram_id = get_telegram_id_from_intent(dev_reference)
        if not telegram_id:
            return {"status": "OK"}

        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
            app_key=APP_KEY,
        )

        if sent_stoken != expected_stoken:
            raise HTTPException(status_code=203, detail="STOKEN inválido")

        # =========================
        # PAGO APROBADO
        # =========================
        if status == "1" and status_detail == "3":
            result = call_bot_backend_confirm_payment(
                intent_uuid=dev_reference,
                transaction_id=transaction_id,
                amount=amount,
                authorization_code=authorization_code,
            )

            if result.get("success"):
                send_telegram_message(
                    telegram_id,
                    (
                        "🎉 <b>PAGO APROBADO</b>\n\n"
                        f"💳 <b>Monto:</b> ${amount}\n"
                        f"🧾 <b>Transacción:</b> {transaction_id}\n"
                        f"🏷 <b>Referencia:</b> {dev_reference}\n\n"
                        "✅ Tu saldo ha sido actualizado\n\n"
                        "Gracias por usar <b>PITIUPI</b> 🚀"
                    ),
                )

        # =========================
        # OTROS ESTADOS (INFO)
        # =========================
        elif status in {"2", "4", "5"}:
            send_telegram_message(
                telegram_id,
                (
                    "⚠️ <b>Estado del pago</b>\n\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n"
                    f"💳 <b>Monto:</b> ${amount}\n"
                    f"📌 <b>Estado:</b> {status}/{status_detail}"
                ),
            )

        return {"status": "OK"}

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error crítico en webhook: {e}", exc_info=True)
        return {"status": "OK"}

# ============================================================
# HEALTH
# ============================================================

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "nuvei_webhook",
        "version": "6.0",
        "timestamp": datetime.utcnow().isoformat(),
        "bot_backend_configured": bool(BOT_BACKEND_URL),
        "internal_api_key_configured": bool(INTERNAL_API_KEY),
    }
