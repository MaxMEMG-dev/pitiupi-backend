# ============================================================
# payments_api.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.5 — Backend Nuvei (Híbrido: Local/Render)
# ============================================================

from fastapi import APIRouter, Request, HTTPException, Header, Depends
import hashlib
import logging
import os
import requests
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional

router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

# ============================================================
# INTENTO DE CARGA DE MÓDULOS DE BASE DE DATOS (MODO V6)
# ============================================================
HAS_DATABASE = False
try:
    from database.session import get_session
    from database.services import payments_service, users_service
    from database.models.payment_intents import PaymentIntentStatus
    HAS_DATABASE = True
    logger.info("✅ Modo V6 Detectado: Uso de base de datos directa habilitado")
except (ImportError, ModuleNotFoundError):
    logger.info("ℹ️ Modo Local/Pruebas: No se detectó carpeta 'database', usando delegación HTTP")

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
if not BOT_BACKEND_URL:
    logger.warning("⚠️ BOT_BACKEND_URL no configurado - Delegación HTTP deshabilitada")

# ============================================================
# HELPERS DE SEGURIDAD Y COMUNICACIÓN
# ============================================================

def verify_internal_key(x_internal_api_key: str = Header(...)):
    """Valida que la llamada provenga del Bot u otro servicio interno."""
    if x_internal_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")

def _internal_headers() -> dict:
    """Headers de autenticación interna"""
    return {
        "X-Internal-API-Key": INTERNAL_API_KEY,
        "Content-Type": "application/json",
    }

def generate_stoken(transaction_id: str, application_code: str, user_id: str, app_key: str) -> str:
    """Fórmula oficial Nuvei: MD5(transaction_id + "_" + application_code + "_" + user_id + "_" + app_key)"""
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()

# ============================================================
# NOTIFICACIONES TELEGRAM
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
    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")

# ============================================================
# LÓGICA DE NEGOCIO (HÍBRIDA)
# ============================================================

def get_telegram_id_from_intent(db_session: Any, intent_uuid: str) -> Optional[int]:
    """Obtiene el telegram_id buscando en DB o preguntando al Bot Backend"""
    # 1. Intentar por DB (si estamos en el Render del Bot)
    if HAS_DATABASE and db_session:
        intent = payments_service.get_payment_intent_by_uuid(intent_uuid, session=db_session)
        if intent:
            user = users_service.get_user_by_id(db_session, intent.user_id)
            return int(user.telegram_id) if user else None

    # 2. Intentar por HTTP (Modo Local/Pruebas)
    if BOT_BACKEND_URL:
        url = f"{BOT_BACKEND_URL}/internal/payments/intent/{intent_uuid}"
        try:
            resp = requests.get(url, headers=_internal_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json().get("telegram_id")
        except Exception as e:
            logger.error(f"❌ Error HTTP obteniendo telegram_id: {e}")
    
    return None

def confirm_payment_logic(
    db_session: Any, 
    intent_uuid: str, 
    transaction_id: str, 
    amount: Decimal, 
    authorization_code: str | None = None
) -> dict:
    """Confirma el pago en la DB o delega al Bot por HTTP"""
    
    # Caso A: Tenemos base de datos (Render con DB)
    if HAS_DATABASE and db_session:
        try:
            # Idempotencia
            intent = payments_service.get_payment_intent_by_uuid(intent_uuid, session=db_session)
            if intent and intent.status == PaymentIntentStatus.COMPLETED:
                return {"success": True, "already_confirmed": True}

            payments_service.confirm_payment_intent_service(
                intent_uuid=intent_uuid,
                provider_tx_id=transaction_id,
                amount_received=float(amount),
                session=db_session,
                authorization_code=authorization_code
            )
            db_session.commit()
            return {"success": True}
        except Exception as e:
            db_session.rollback()
            logger.error(f"❌ Error confirmando en DB local: {e}")
            return {"success": False}

    # Caso B: No hay DB (Modo Local / Pruebas), delegamos por HTTP
    if BOT_BACKEND_URL:
        url = f"{BOT_BACKEND_URL}/internal/payments/confirm"
        payload = {
            "intent_uuid": intent_uuid,
            "provider_tx_id": transaction_id,
            "amount_received": float(amount),
            "authorization_code": authorization_code,
        }
        try:
            resp = requests.post(url, json=payload, headers=_internal_headers(), timeout=15)
            if resp.status_code == 200: return {"success": True}
            if resp.status_code == 409: return {"success": True, "already_confirmed": True}
        except Exception as e:
            logger.error(f"❌ Error confirmando pago por HTTP: {e}")
    
    return {"success": False}

# ============================================================
# WEBHOOK NUVEI
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    """🔥 Webhook oficial de Nuvei"""
    # Si tenemos DB, intentamos obtener sesión, si no, None
    db = None
    if HAS_DATABASE:
        from database.session import get_session
        db = get_session()

    try:
        payload = await request.json()
        logger.info("=" * 60)
        logger.info("🔥 WEBHOOK NUVEI RECIBIDO")
        
        tx = payload.get("transaction")
        if not tx: return {"status": "OK"}

        # Datos Críticos
        transaction_id = tx.get("id")
        dev_reference = tx.get("dev_reference")
        application_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount_raw = tx.get("amount")
        sent_stoken = tx.get("stoken")
        authorization_code = tx.get("authorization_code")

        if not all([transaction_id, dev_reference, application_code, amount_raw]):
            logger.warning("⚠️ Payload incompleto")
            return {"status": "OK"}

        amount = Decimal(str(amount_raw))

        # 1. Obtener Identidad
        telegram_id = get_telegram_id_from_intent(db, dev_reference)
        if not telegram_id:
            logger.warning(f"⚠️ Sin telegram_id para {dev_reference}")
            return {"status": "OK"}

        # 2. Validar STOKEN
        expected_stoken = generate_stoken(transaction_id, application_code, str(telegram_id), APP_KEY)
        if sent_stoken != expected_stoken:
            logger.error(f"❌ STOKEN INVÁLIDO para usuario {telegram_id}")
            raise HTTPException(status_code=203, detail="STOKEN inválido")

        # 3. Procesar Aprobación
        if status == "1" and status_detail == "3":
            logger.info("🎉 PAGO APROBADO")
            result = confirm_payment_logic(db, dev_reference, transaction_id, amount, authorization_code)
            
            if result.get("success"):
                if not result.get("already_confirmed"):
                    send_telegram_message(
                        telegram_id,
                        f"🎉 <b>¡PAGO APROBADO!</b>\n\n"
                        f"💳 <b>Monto:</b> ${amount} USD\n"
                        f"🧾 <b>Transacción:</b> {transaction_id}\n\n"
                        "✅ <b>Tu saldo ha sido actualizado.</b>"
                    )
            else:
                send_telegram_message(telegram_id, "⚠️ Error procesando pago. Contacta a soporte.")

        # 4. Otros Estados
        elif status in {"0", "2", "4", "5"}:
            status_map = {"0": "⏳ Pendiente", "2": "❌ Cancelado", "4": "❌ Rechazado", "5": "⏰ Expirado"}
            status_text = status_map.get(status, "❓ Desconocido")
            send_telegram_message(telegram_id, f"ℹ️ <b>Estado del pago: {status_text}</b>")

        return {"status": "OK"}

    except Exception as e:
        logger.error(f"❌ Error en webhook: {e}", exc_info=True)
        return {"status": "OK"}
    finally:
        if db: db.close()

# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mode": "V6-Native" if HAS_DATABASE else "Legacy-HTTP-Proxy",
        "db_available": HAS_DATABASE,
        "timestamp": datetime.utcnow().isoformat()
    }
