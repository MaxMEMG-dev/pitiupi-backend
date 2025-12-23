# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.0 — Backend Nuvei (validación STOKEN + delegación)
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
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# Validación crítica
if not APP_KEY:
    raise RuntimeError("❌ NUVEI_APP_KEY_SERVER es obligatorio")

if not BOT_BACKEND_URL:
    raise RuntimeError("❌ BOT_BACKEND_URL es obligatorio")

if not INTERNAL_API_KEY:
    raise RuntimeError("❌ INTERNAL_API_KEY es obligatorio")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones Telegram desactivadas")

logger.info("✅ Webhook Nuvei configurado")

# ============================================================
# HELPERS INTERNOS
# ============================================================

def _internal_headers() -> dict:
    """Headers de autenticación interna entre servicios"""
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
    Genera STOKEN según especificación oficial Nuvei:
    
    Formula: MD5(transaction_id + "_" + application_code + "_" + user_id + "_" + app_key)
    
    Args:
        transaction_id: ID de transacción Nuvei
        application_code: Application code de Nuvei
        user_id: ID del usuario (telegram_id)
        app_key: Secret key de Nuvei
    
    Returns:
        str: Hash MD5 en hexadecimal (lowercase)
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()

# ============================================================
# TELEGRAM NOTIFICATIONS (OPCIONAL)
# ============================================================

def send_telegram_message(chat_id: int, text: str) -> None:
    """
    Envía mensaje por Telegram (si BOT_TOKEN está configurado)
    
    Esta función es best-effort (si falla, solo se loggea)
    """
    if not BOT_TOKEN:
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        
        resp = requests.post(url, json=payload, timeout=10)
        
        if resp.status_code == 200:
            logger.info(f"✅ Mensaje Telegram enviado a {chat_id}")
        else:
            logger.warning(f"⚠️ Error enviando Telegram: {resp.status_code}")

    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")

# ============================================================
# BOT BACKEND CALLS
# ============================================================

def get_telegram_id_from_intent(intent_uuid: str) -> int | None:
    """
    Obtiene el telegram_id asociado a un intent_uuid
    
    Returns:
        int: Telegram ID si se encuentra
        None: Si no existe o hay error
    """
    url = f"{BOT_BACKEND_URL}/internal/payments/intent/{intent_uuid}"

    logger.info(f"📞 Obteniendo telegram_id | Intent: {intent_uuid}")

    try:
        resp = requests.get(
            url,
            headers=_internal_headers(),
            timeout=10,
        )

        if resp.status_code == 200:
            data = resp.json()
            telegram_id = data.get("telegram_id")
            logger.info(f"✅ Telegram ID obtenido: {telegram_id}")
            return telegram_id

        logger.error(f"❌ Error obteniendo intent: {resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"❌ Error llamando Bot Backend: {e}")
        return None


def call_bot_backend_confirm_payment(
    intent_uuid: str,
    transaction_id: str,
    amount: Decimal,
    authorization_code: str | None = None
) -> dict:
    """
    Confirma el pago en el Bot Backend (actualiza balance + ledger)
    
    Args:
        intent_uuid: UUID del PaymentIntent
        transaction_id: ID de transacción Nuvei
        amount: Monto recibido
        authorization_code: Código de autorización (opcional)
    
    Returns:
        dict: {"success": bool, "already_confirmed": bool (opcional)}
    """
    url = f"{BOT_BACKEND_URL}/internal/payments/confirm"

    payload = {
        "intent_uuid": intent_uuid,
        "provider_tx_id": transaction_id,
        "amount_received": float(amount),
        "authorization_code": authorization_code,
    }

    logger.info(f"📞 Confirmando pago en Bot | Intent: {intent_uuid}")

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=30,
        )

        if resp.status_code == 200:
            logger.info("✅ Pago confirmado en Bot Backend")
            return {"success": True}

        if resp.status_code == 409:
            # Idempotencia: pago ya confirmado previamente
            logger.info("ℹ️ Pago ya confirmado (idempotencia)")
            return {"success": True, "already_confirmed": True}

        logger.error(f"❌ Error confirmando pago: {resp.status_code} | {resp.text[:200]}")
        return {"success": False}

    except Exception as e:
        logger.error(f"❌ Error crítico confirmando pago: {e}", exc_info=True)
        return {"success": False}

# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    """
    🔥 Webhook oficial de Nuvei
    
    Flujo:
    1. Recibe POST de Nuvei con datos de transacción
    2. Valida STOKEN (seguridad crítica)
    3. Si pago aprobado (status=1, status_detail=3):
       - Confirma pago en Bot Backend
       - Envía notificación Telegram
    4. Si pago rechazado/pendiente:
       - Notifica estado por Telegram
    5. SIEMPRE responde HTTP 200 a Nuvei
    
    Returns:
        dict: {"status": "OK"} (siempre)
    """
    try:
        # ============================================================
        # 1️⃣ PARSEAR PAYLOAD
        # ============================================================

        payload = await request.json()
        logger.info("=" * 60)
        logger.info("🔥 Webhook Nuvei recibido")
        logger.debug(f"📦 Payload: {payload}")

        tx = payload.get("transaction")
        if not tx:
            logger.warning("⚠️ Webhook sin campo 'transaction'")
            return {"status": "OK"}

        # Extraer campos críticos
        transaction_id = tx.get("id")
        dev_reference = tx.get("dev_reference")  # Este es el intent_uuid
        application_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount_raw = tx.get("amount")
        sent_stoken = tx.get("stoken")
        authorization_code = tx.get("authorization_code")

        logger.info(f"🆔 Transaction ID: {transaction_id}")
        logger.info(f"📋 Dev Reference: {dev_reference}")
        logger.info(f"📊 Status: {status}/{status_detail}")
        logger.info(f"💵 Amount: {amount_raw}")

        # Validar campos requeridos
        if not all([transaction_id, dev_reference, application_code, amount_raw]):
            logger.warning("⚠️ Webhook con datos incompletos")
            return {"status": "OK"}

        amount = Decimal(str(amount_raw))

        # ============================================================
        # 2️⃣ OBTENER TELEGRAM_ID
        # ============================================================

        telegram_id = get_telegram_id_from_intent(dev_reference)
        if not telegram_id:
            logger.warning(f"⚠️ No se encontró telegram_id para intent {dev_reference}")
            return {"status": "OK"}

        logger.info(f"👤 Telegram ID: {telegram_id}")

        # ============================================================
        # 3️⃣ VALIDAR STOKEN (SEGURIDAD CRÍTICA)
        # ============================================================

        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
            app_key=APP_KEY,
        )

        logger.info(f"🔐 STOKEN recibido: {sent_stoken}")
        logger.info(f"🔐 STOKEN esperado: {expected_stoken}")

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN INVÁLIDO - Webhook rechazado")
            raise HTTPException(status_code=203, detail="STOKEN inválido")

        logger.info("✅ STOKEN validado correctamente")

        # ============================================================
        # 4️⃣ PROCESAR SEGÚN ESTADO
        # ============================================================

        # 🎉 PAGO APROBADO
        if status == "1" and status_detail == "3":
            logger.info("🎉 PAGO APROBADO - Procesando confirmación")

            result = call_bot_backend_confirm_payment(
                intent_uuid=dev_reference,
                transaction_id=transaction_id,
                amount=amount,
                authorization_code=authorization_code,
            )

            if result.get("success"):
                logger.info("✅ Pago confirmado exitosamente")

                # Notificar usuario por Telegram
                send_telegram_message(
                    telegram_id,
                    (
                        "🎉 <b>¡PAGO APROBADO!</b>\n\n"
                        f"💳 <b>Monto:</b> ${amount} USD\n"
                        f"🧾 <b>Transacción:</b> {transaction_id}\n"
                        f"🏷 <b>Referencia:</b> {dev_reference}\n"
                        f"✅ <b>Autorización:</b> {authorization_code or 'N/A'}\n\n"
                        "✅ <b>Tu saldo ha sido actualizado</b>\n\n"
                        "Gracias por usar <b>PITIUPI</b> 🚀"
                    ),
                )
            else:
                logger.error("❌ Error confirmando pago en Bot Backend")
                send_telegram_message(
                    telegram_id,
                    (
                        "⚠️ <b>Error procesando pago</b>\n\n"
                        f"🧾 <b>Transacción:</b> {transaction_id}\n"
                        f"💵 <b>Monto:</b> ${amount} USD\n\n"
                        "Por favor contacta a soporte."
                    ),
                )

        # 🔄 PAGO PENDIENTE / RECHAZADO / CANCELADO
        elif status in {"0", "2", "4", "5"}:
            status_map = {
                "0": "⏳ Pendiente",
                "2": "❌ Cancelado",
                "4": "❌ Rechazado",
                "5": "⏰ Expirado",
            }
            status_text = status_map.get(status, "❓ Desconocido")

            logger.info(f"ℹ️ Pago en estado: {status_text}")

            send_telegram_message(
                telegram_id,
                (
                    f"ℹ️ <b>Estado del pago: {status_text}</b>\n\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n"
                    f"💳 <b>Monto:</b> ${amount} USD\n"
                    f"📌 <b>Estado:</b> {status}/{status_detail}\n\n"
                    "Si necesitas ayuda, contacta a soporte."
                ),
            )

        # ❓ ESTADO DESCONOCIDO
        else:
            logger.warning(f"⚠️ Estado no manejado: {status}/{status_detail}")

        logger.info("=" * 60)
        return {"status": "OK"}

    except HTTPException:
        # Re-lanzar HTTPException (203 para STOKEN inválido)
        raise

    except Exception as e:
        logger.error(f"❌ Error crítico en webhook: {e}", exc_info=True)
        # SIEMPRE responder 200 a Nuvei para evitar reintentos
        return {"status": "OK"}

# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check():
    """Health check del módulo webhook"""
    return {
        "status": "healthy",
        "service": "nuvei_webhook",
        "version": "6.0",
        "timestamp": datetime.utcnow().isoformat(),
        "bot_backend_configured": bool(BOT_BACKEND_URL),
        "internal_api_key_configured": bool(INTERNAL_API_KEY),
        "telegram_notifications": bool(BOT_TOKEN),
    }

# ============================================================
# END OF FILE
# ============================================================
