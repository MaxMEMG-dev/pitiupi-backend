# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.3 — Backend Nuvei (validación STOKEN)
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
APP_CODE = os.getenv("NUVEI_APP_CODE_SERVER")
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Validación crítica
if not APP_KEY:
    raise RuntimeError("❌ NUVEI_APP_KEY_SERVER es obligatorio")

if not APP_CODE:
    raise RuntimeError("❌ NUVEI_APP_CODE_SERVER es obligatorio")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones Telegram desactivadas")

logger.info("✅ Webhook Nuvei configurado")

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
# TELEGRAM NOTIFICATIONS
# ============================================================

def send_telegram_message(chat_id: int, text: str) -> None:
    """
    Envía mensaje por Telegram (si BOT_TOKEN está configurado)
    
    Esta función es best-effort (si falla, solo se loggea)
    """
    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN no configurado, no se puede enviar mensaje")
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
            logger.warning(f"⚠️ Error enviando Telegram: {resp.status_code} - {resp.text[:200]}")

    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")

# ============================================================
# HELPER: EXTRAER TELEGRAM_ID DEL DEV_REFERENCE
# ============================================================

def extract_telegram_id_from_dev_reference(dev_reference: str) -> int | None:
    """
    Extrae el telegram_id del dev_reference
    
    Formato esperado: PITIUPI-{telegram_id}-{timestamp}
    Ejemplo: PITIUPI-123456789-1734567890
    
    Args:
        dev_reference: Referencia de desarrollador
    
    Returns:
        int: Telegram ID si se puede extraer
        None: Si el formato es inválido
    """
    try:
        # Formato: PITIUPI-{telegram_id}-{timestamp}
        parts = dev_reference.split("-")
        if len(parts) >= 2 and parts[0] == "PITIUPI":
            telegram_id = int(parts[1])
            logger.info(f"✅ Telegram ID extraído de dev_reference: {telegram_id}")
            return telegram_id
    except (ValueError, IndexError) as e:
        logger.error(f"❌ Error extrayendo telegram_id de '{dev_reference}': {e}")
    
    return None

# ============================================================
# DATABASE INTEGRATION (OPCIONAL)
# ============================================================

try:
    from database.session import SessionLocal
    from database.models.payment_intents import PaymentIntent, PaymentIntentStatus
    DB_AVAILABLE = True
    logger.info("✅ Base de datos disponible para actualizar payment intents")
except ImportError:
    DB_AVAILABLE = False
    logger.warning("⚠️ Base de datos no disponible - Solo notificaciones Telegram")

def update_payment_intent_in_db(
    provider_order_id: str,
    status: PaymentIntentStatus,
    transaction_id: str,
    authorization_code: str | None = None
) -> bool:
    """
    Actualiza el estado del payment intent en la base de datos
    
    Args:
        provider_order_id: Order ID de Nuvei
        status: Nuevo estado del payment intent
        transaction_id: ID de transacción de Nuvei
        authorization_code: Código de autorización (opcional)
    
    Returns:
        bool: True si se actualizó correctamente, False en caso contrario
    """
    if not DB_AVAILABLE:
        logger.warning("⚠️ DB no disponible, no se puede actualizar payment intent")
        return False
    
    db = SessionLocal()
    try:
        # Buscar payment intent por provider_order_id
        intent = db.query(PaymentIntent).filter(
            PaymentIntent.provider_order_id == provider_order_id
        ).first()
        
        if not intent:
            logger.error(f"❌ Payment intent no encontrado: order_id={provider_order_id}")
            return False
        
        # Actualizar estado
        intent.status = status
        
        # Actualizar detalles
        if not intent.details:
            intent.details = {}
        
        intent.details["transaction_id"] = transaction_id
        if authorization_code:
            intent.details["authorization_code"] = authorization_code
        intent.details["updated_at"] = datetime.utcnow().isoformat()
        
        db.commit()
        logger.info(f"✅ Payment intent actualizado: {provider_order_id} → {status.value}")
        return True
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error actualizando payment intent: {e}", exc_info=True)
        return False
    finally:
        db.close()

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
    3. Extrae telegram_id del dev_reference
    4. Si pago aprobado (status=1, status_detail=3):
       - Actualiza payment intent en DB (si disponible)
       - Envía notificación Telegram
    5. Si pago rechazado/pendiente:
       - Actualiza payment intent en DB (si disponible)
       - Notifica estado por Telegram
    6. SIEMPRE responde HTTP 200 a Nuvei
    
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
        logger.debug(f"📦 Payload completo: {payload}")

        tx = payload.get("transaction")
        if not tx:
            logger.warning("⚠️ Webhook sin campo 'transaction'")
            return {"status": "OK"}

        # Extraer campos críticos
        transaction_id = tx.get("id")
        order_id = tx.get("order_id")  # Este es el provider_order_id
        dev_reference = tx.get("dev_reference")
        application_code = tx.get("application_code")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount_raw = tx.get("amount")
        sent_stoken = tx.get("stoken")
        authorization_code = tx.get("authorization_code")

        logger.info(f"🆔 Transaction ID: {transaction_id}")
        logger.info(f"📦 Order ID: {order_id}")
        logger.info(f"📋 Dev Reference: {dev_reference}")
        logger.info(f"📊 Status: {status}/{status_detail}")
        logger.info(f"💵 Amount: {amount_raw}")

        # Validar campos requeridos
        if not all([transaction_id, dev_reference, application_code, amount_raw]):
            logger.warning("⚠️ Webhook con datos incompletos")
            return {"status": "OK"}

        amount = Decimal(str(amount_raw))

        # ============================================================
        # 2️⃣ EXTRAER TELEGRAM_ID DEL DEV_REFERENCE
        # ============================================================

        telegram_id = extract_telegram_id_from_dev_reference(dev_reference)
        if not telegram_id:
            logger.error(f"❌ No se pudo extraer telegram_id de dev_reference: {dev_reference}")
            return {"status": "OK"}

        logger.info(f"👤 Telegram ID extraído: {telegram_id}")

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
            logger.error(f"❌ Datos usados: tx_id={transaction_id}, app_code={application_code}, user_id={telegram_id}")
            raise HTTPException(status_code=203, detail="STOKEN inválido")

        logger.info("✅ STOKEN validado correctamente")

        # ============================================================
        # 4️⃣ PROCESAR SEGÚN ESTADO
        # ============================================================

        # 🎉 PAGO APROBADO
        if status == "1" and status_detail == "3":
            logger.info("🎉 PAGO APROBADO - Procesando confirmación")

            # Actualizar en DB si está disponible
            if DB_AVAILABLE and order_id:
                db_updated = update_payment_intent_in_db(
                    provider_order_id=order_id,
                    status=PaymentIntentStatus.COMPLETED,
                    transaction_id=transaction_id,
                    authorization_code=authorization_code
                )
                if db_updated:
                    logger.info("✅ Payment intent actualizado en DB")
                else:
                    logger.warning("⚠️ No se pudo actualizar payment intent en DB")

            # Notificar usuario por Telegram
            send_telegram_message(
                telegram_id,
                (
                    "🎉 <b>¡PAGO APROBADO!</b>\n\n"
                    f"💳 <b>Monto:</b> ${amount} USD\n"
                    f"🧾 <b>Transacción:</b> {transaction_id}\n"
                    f"🏷 <b>Referencia:</b> {dev_reference}\n"
                    f"✅ <b>Autorización:</b> {authorization_code or 'N/A'}\n\n"
                    "✅ <b>Tu pago ha sido procesado</b>\n\n"
                    "Gracias por usar <b>PITIUPI</b> 🚀"
                ),
            )

        # 🔄 PAGO PENDIENTE
        elif status == "0":
            logger.info("⏳ Pago pendiente")
            
            if DB_AVAILABLE and order_id:
                update_payment_intent_in_db(
                    provider_order_id=order_id,
                    status=PaymentIntentStatus.PENDING,
                    transaction_id=transaction_id
                )

            send_telegram_message(
                telegram_id,
                (
                    "⏳ <b>Pago Pendiente</b>\n\n"
                    f"💵 <b>Monto:</b> ${amount} USD\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n\n"
                    "Tu pago está siendo procesado. Te notificaremos cuando se complete."
                ),
            )

        # ❌ PAGO RECHAZADO
        elif status == "4":
            logger.info("❌ Pago rechazado")
            
            if DB_AVAILABLE and order_id:
                update_payment_intent_in_db(
                    provider_order_id=order_id,
                    status=PaymentIntentStatus.FAILED,
                    transaction_id=transaction_id
                )

            send_telegram_message(
                telegram_id,
                (
                    "❌ <b>Pago Rechazado</b>\n\n"
                    f"💵 <b>Monto:</b> ${amount} USD\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n\n"
                    "Tu pago no pudo ser procesado. Por favor intenta nuevamente o contacta a soporte."
                ),
            )

        # 🚫 PAGO CANCELADO
        elif status == "2":
            logger.info("🚫 Pago cancelado")
            
            if DB_AVAILABLE and order_id:
                update_payment_intent_in_db(
                    provider_order_id=order_id,
                    status=PaymentIntentStatus.CANCELLED,
                    transaction_id=transaction_id
                )

            send_telegram_message(
                telegram_id,
                (
                    "🚫 <b>Pago Cancelado</b>\n\n"
                    f"💵 <b>Monto:</b> ${amount} USD\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n\n"
                    "El pago fue cancelado."
                ),
            )

        # ⏰ PAGO EXPIRADO
        elif status == "5":
            logger.info("⏰ Pago expirado")
            
            if DB_AVAILABLE and order_id:
                update_payment_intent_in_db(
                    provider_order_id=order_id,
                    status=PaymentIntentStatus.EXPIRED,
                    transaction_id=transaction_id
                )

            send_telegram_message(
                telegram_id,
                (
                    "⏰ <b>Pago Expirado</b>\n\n"
                    f"💵 <b>Monto:</b> ${amount} USD\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n\n"
                    "El tiempo para completar el pago ha expirado. Por favor genera un nuevo link de pago."
                ),
            )

        # ❓ ESTADO DESCONOCIDO
        else:
            logger.warning(f"⚠️ Estado no manejado: {status}/{status_detail}")
            
            send_telegram_message(
                telegram_id,
                (
                    f"ℹ️ <b>Actualización de Pago</b>\n\n"
                    f"💵 <b>Monto:</b> ${amount} USD\n"
                    f"🧾 <b>Referencia:</b> {dev_reference}\n"
                    f"📌 <b>Estado:</b> {status}/{status_detail}\n\n"
                    "Si necesitas ayuda, contacta a soporte."
                ),
            )

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
        "version": "6.3",
        "timestamp": datetime.utcnow().isoformat(),
        "features": [
            "✅ STOKEN validation",
            "✅ Telegram notifications" if BOT_TOKEN else "⚠️ Telegram not configured",
            "✅ DB integration" if DB_AVAILABLE else "⚠️ DB not available",
        ],
        "database_mode": "CONNECTED" if DB_AVAILABLE else "STATELESS",
    }

# ============================================================
# END OF FILE
# ============================================================
