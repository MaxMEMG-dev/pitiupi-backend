# ============================================================
# api/routes/payments_api.py — Receptor de Webhooks Nuvei
# PITIUPI v6.0 — Backend Nuvei (validación STOKEN + delegación)
# ============================================================

from fastapi import APIRouter, Request, HTTPException, Depends, Header
import hashlib
import logging
import os
import requests
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

# Integración con el Core de PITIUPI V6
from database.session import get_session
from database.services import payments_service, users_service
from database.models.payment_intents import PaymentIntentStatus

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
    logger.error("❌ NUVEI_APP_KEY_SERVER es obligatorio")

if not INTERNAL_API_KEY:
    logger.error("❌ INTERNAL_API_KEY es obligatorio")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones Telegram desactivadas")

# ============================================================
# HELPERS Y SEGURIDAD
# ============================================================

def verify_internal_key(x_internal_api_key: str = Header(...)):
    """Valida que la llamada provenga del Bot u otro servicio interno."""
    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")

def _internal_headers() -> dict:
    """Headers para compatibilidad con servicios que aún usen peticiones HTTP"""
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
    Formula: MD5(transaction_id + "_" + application_code + "_" + user_id + "_" + app_key)
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()

# ============================================================
# TELEGRAM NOTIFICATIONS
# ============================================================

def send_telegram_message(chat_id: int, text: str) -> None:
    """Envía mensaje por Telegram (best-effort)"""
    if not BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info(f"✅ Mensaje Telegram enviado a {chat_id}")
        else:
            logger.warning(f"⚠️ Error enviando Telegram: {resp.status_code}")
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")

# ============================================================
# BOT BACKEND CALLS (ADAPTADAS A SERVICES INTERNOS V6)
# ============================================================

def get_telegram_id_from_intent(db: Session, intent_uuid: str) -> Optional[int]:
    """Obtiene el telegram_id directamente de la DB para evitar latencia HTTP"""
    intent = payments_service.get_payment_intent_by_uuid(intent_uuid, session=db)
    if not intent:
        return None
    user = users_service.get_user_by_id(db, intent.user_id)
    return int(user.telegram_id) if user else None

def call_bot_backend_confirm_payment(
    db: Session,
    intent_uuid: str,
    transaction_id: str,
    amount: Decimal,
    authorization_code: str | None = None
) -> dict:
    """Ejecuta la confirmación financiera en el sistema local"""
    try:
        # Verificamos si ya está confirmado para cumplir con la lógica de 409 (Conflict)
        intent = payments_service.get_payment_intent_by_uuid(intent_uuid, session=db)
        if intent and intent.status == PaymentIntentStatus.COMPLETED:
            return {"success": True, "already_confirmed": True}

        # Ejecutamos el servicio que actualiza balance y crea el ledger
        payments_service.confirm_payment_intent_service(
            intent_uuid=intent_uuid,
            provider_tx_id=transaction_id,
            amount_received=float(amount),
            session=db,
            authorization_code=authorization_code
        )
        db.commit() # Importante en V6
        return {"success": True}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error confirmando pago: {e}")
        return {"success": False}

# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request, db: Session = Depends(get_session)):
    """🔥 Webhook oficial de Nuvei"""
    try:
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
        dev_reference = tx.get("dev_reference")  # intent_uuid
        application_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount_raw = tx.get("amount")
        sent_stoken = tx.get("stoken")
        authorization_code = tx.get("authorization_code")

        if not all([transaction_id, dev_reference, application_code, amount_raw]):
            logger.warning("⚠️ Webhook con datos incompletos")
            return {"status": "OK"}

        amount = Decimal(str(amount_raw))

        # Obtener Telegram ID
        telegram_id = get_telegram_id_from_intent(db, dev_reference)
        if not telegram_id:
            logger.warning(f"⚠️ No se encontró telegram_id para intent {dev_reference}")
            return {"status": "OK"}

        # Validar STOKEN
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
            app_key=APP_KEY,
        )

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN INVÁLIDO - Webhook rechazado")
            raise HTTPException(status_code=203, detail="STOKEN inválido")

        # PROCESAR SEGÚN ESTADO
        if status == "1" and status_detail == "3":
            logger.info("🎉 PAGO APROBADO - Procesando confirmación")

            result = call_bot_backend_confirm_payment(
                db=db,
                intent_uuid=dev_reference,
                transaction_id=transaction_id,
                amount=amount,
                authorization_code=authorization_code,
            )

            if result.get("success"):
                logger.info("✅ Pago confirmado exitosamente")
                if not result.get("already_confirmed"):
                    send_telegram_message(
                        telegram_id,
                        (
                            "🎉 <b>¡PAGO APROBADO!</b>\n\n"
                            f"💳 <b>Monto:</b> ${amount} USD\n"
                            f"🧾 <b>Transacción:</b> {transaction_id}\n"
                            f"✅ <b>Autorización:</b> {authorization_code or 'N/A'}\n\n"
                            "✅ <b>Tu saldo ha sido actualizado</b>\n\n"
                            "Gracias por usar <b>PITIUPI</b> 🚀"
                        ),
                    )
            else:
                send_telegram_message(
                    telegram_id,
                    "⚠️ <b>Error procesando pago</b>\n\nPor favor contacta a soporte."
                )

        elif status in {"0", "2", "4", "5"}:
            status_map = {"0": "⏳ Pendiente", "2": "❌ Cancelado", "4": "❌ Rechazado", "5": "⏰ Expirado"}
            status_text = status_map.get(status, "❓ Desconocido")
            send_telegram_message(
                telegram_id,
                f"ℹ️ <b>Estado del pago: {status_text}</b>\n\nReferencia: {dev_reference}"
            )

        return {"status": "OK"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error crítico en webhook: {e}", exc_info=True)
        return {"status": "OK"}

# ============================================================
# ENDPOINTS ADICIONALES (BOT COMPATIBILITY)
# ============================================================

@router.post("/internal/payments/create", dependencies=[Depends(verify_internal_key)])
async def create_intent_for_bot(payload: Dict[str, Any], db: Session = Depends(get_session)):
    """Permite al bot crear una intención de pago"""
    t_id = payload.get("telegram_id")
    amt = payload.get("amount")
    user = users_service.get_user_by_telegram_id(db, str(t_id))
    if not user: raise HTTPException(status_code=404)
    
    intent = payments_service.create_payment_intent_service(user.id, float(amt), db)
    db.commit()
    return intent

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "nuvei_webhook_adapted",
        "version": "6.0",
        "timestamp": datetime.utcnow().isoformat()
    }
