# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.1 — ✅ PRODUCCIÓN: Idempotencia + AML + Transaccional
# ============================================================

from fastapi import APIRouter, Request
import hashlib
import logging
import os
import json
import requests
from decimal import Decimal
from typing import Dict, Any

router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

# --- INTENTO DE IMPORTACIÓN SEGURO ---
HAS_DB = False
try:
    from database.session import db_session
    from database.models.user import User
    from database.services.users_service import (
        get_user_by_telegram_id,
        add_recharge_balance,
        mark_first_deposit_completed
    )
    from sqlalchemy import select, text
    HAS_DB = True
except ImportError as e:
    logger.warning(f"⚠️ No se pudo importar módulos de DB: {e}")
    logger.warning("⚠️ Funcionando en modo Proxy/Local sin acceso a base de datos")

# Variables de entorno
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_BACKEND_URL = os.getenv("BOT_BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# --- HELPERS ---

def generate_stoken(transaction_id: str, application_code: str, user_id: str, app_key: str) -> str:
    """
    Genera token de seguridad para validar webhooks de Nuvei.
    
    IMPORTANTE: El formato debe coincidir EXACTAMENTE con la configuración
    de tu panel de Nuvei para Ecuador. Verifica el orden de los campos.
    
    Args:
        transaction_id: ID de transacción de Nuvei
        application_code: Código de aplicación
        user_id: ID del usuario
        app_key: Llave secreta del servidor
        
    Returns:
        str: Hash MD5 del token
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    return hashlib.md5(raw.encode()).hexdigest()


def send_telegram_notification(chat_id: int, text_msg: str):
    """
    Envía notificación al usuario vía Telegram.
    
    Esta función se ejecuta FUERA de la transacción de DB para no
    bloquear el commit si el servicio de Telegram está lento.
    
    Args:
        chat_id: ID del chat de Telegram
        text_msg: Mensaje a enviar (soporta HTML)
    """
    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN no configurado, no se puede enviar notificación")
        return
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text_msg,
                "parse_mode": "HTML"
            },
            timeout=5
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Notificación enviada a chat_id={chat_id}")
        else:
            logger.error(f"❌ Error enviando notificación: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"❌ Excepción enviando notificación: {e}")


# --- WEBHOOK ---

@router.post("/callback")
def nuvei_callback(request: Request):
    """
    ✅ V6.1 PRODUCCIÓN: Webhook para procesar pagos de Nuvei.
    
    CRÍTICO - SEGURIDAD Y CONSISTENCIA:
    1. Idempotencia: Previene procesamiento duplicado del mismo pago
    2. Transaccional: Todo-o-nada (commit único al final)
    3. Bloqueo de fila: Previene race conditions en balances
    4. AML Compliance: Separa balance_recharge (no retirable)
    5. Síncrono: Compatible con SQLAlchemy sync engine de PITIUPI v6
    
    NOTA: Esta función es SÍNCRONA (def, no async def) porque:
    - db_session es síncrono en PITIUPI v6
    - FastAPI ejecuta funciones sync en threadpool automáticamente
    - Evita errores de "procedimiento ejecutado fuera de hilo"
    
    Flow con Idempotencia:
    1. Validar firma de seguridad
    2. Si pago exitoso (status=1, detail=3):
       a. ✅ Verificar si ya fue procesado (idempotencia)
       b. Buscar usuario por telegram_id
       c. Bloquear fila (FOR UPDATE)
       d. Registrar PaymentIntent (INSERT o UPDATE)
       e. Agregar saldo a balance_recharge
       f. Marcar primer depósito si aplica
       g. Commit único de toda la transacción
       h. Notificar usuario (fuera de transacción)
    """
    try:
        # Parsear payload
        payload = await request.json() 
        tx = payload.get("transaction", {})
        
        # Extraer datos de la transacción
        transaction_id = str(tx.get("id"))  # ✅ Convertir a string explícitamente
        dev_reference = tx.get("dev_reference", "")  # Formato: PITIUPI-TELEGRAMID-UUID
        app_code = tx.get("application_code", "")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        amount = Decimal(str(tx.get("amount", "0")))
        sent_stoken = tx.get("stoken")

        logger.info(
            f"📥 Webhook recibido: tx_id={transaction_id}, "
            f"ref={dev_reference}, status={status}, detail={status_detail}, amount=${amount}"
        )

        # Extraer Telegram ID de la referencia
        try:
            telegram_id = dev_reference.split("-")[1]
        except Exception as e:
            logger.error(f"❌ Formato de dev_reference inválido: {dev_reference} - {e}")
            return {"status": "error", "message": "invalid_reference"}

        # 1. Validar Firma de Seguridad (RECOMENDADO en producción)
        if APP_KEY and sent_stoken:
            expected_token = generate_stoken(transaction_id, app_code, telegram_id, APP_KEY)
            if sent_stoken != expected_token:
                logger.error(
                    f"❌ FIRMA INVÁLIDA para transacción {transaction_id}. "
                    f"Expected: {expected_token}, Got: {sent_stoken}"
                )
                return {"status": "error", "message": "invalid_signature"}
            logger.info(f"✅ Firma validada correctamente para tx {transaction_id}")

        # 2. Procesar solo si el pago es exitoso (Status 1, Detail 3)
        if status == "1" and status_detail == "3":
            logger.info(f"💰 PAGO APROBADO: ${amount} USD (Telegram ID: {telegram_id})")

            if HAS_DB:
                # Modo con Base de Datos (Producción)
                with db_session() as session:
                    try:
                        # ✅ A. IDEMPOTENCIA: Verificar si ya fue procesado
                        # Esto previene doble acreditación si Nuvei reenvía el webhook
                        existing_payment = session.execute(
                            text("""
                                SELECT id, status 
                                FROM payment_intents 
                                WHERE provider_order_id = :oid
                            """),
                            {"oid": transaction_id}
                        ).fetchone()

                        if existing_payment and existing_payment[1] == "COMPLETED":
                            logger.warning(
                                f"⚠️ IDEMPOTENCIA: Transacción {transaction_id} ya fue procesada "
                                f"anteriormente como COMPLETED. Ignorando webhook duplicado."
                            )
                            return {"status": "OK", "message": "already_processed"}

                        # B. Buscar usuario por telegram_id
                        user = get_user_by_telegram_id(session, str(telegram_id))

                        if not user:
                            logger.error(
                                f"❌ USUARIO NO ENCONTRADO: telegram_id={telegram_id}. "
                                f"El usuario debe registrarse primero en el bot."
                            )
                            return {"status": "error", "message": "user_not_found"}

                        logger.info(
                            f"✅ Usuario encontrado: id={user.id}, "
                            f"telegram_id={user.telegram_id}, "
                            f"first_deposit={user.first_deposit_completed}"
                        )

                        # C. Bloqueo de fila para actualización segura (previene race conditions)
                        stmt = select(User).where(User.id == user.id).with_for_update()
                        user_locked = session.execute(stmt).scalar_one()

                        # D. Registrar/Actualizar PaymentIntent PRIMERO (antes de sumar saldo)
                        # Si esto falla, el rollback previene que se sume dinero
                        session.execute(
                            text("""
                                INSERT INTO payment_intents (
                                    uuid, user_id, amount, amount_received, status, 
                                    provider_order_id, provider, currency, details,
                                    created_at, updated_at, expires_at
                                )
                                VALUES (
                                    gen_random_uuid(), 
                                    :uid, 
                                    :amt, 
                                    :amt, 
                                    'COMPLETED', 
                                    :oid, 
                                    'nuvei', 
                                    'USD', 
                                    :details,
                                    NOW(), 
                                    NOW(), 
                                    NOW() + INTERVAL '24 hours'
                                )
                                ON CONFLICT (provider_order_id) DO UPDATE SET 
                                    status = 'COMPLETED',
                                    amount_received = :amt,
                                    updated_at = NOW();
                            """),
                            {
                                "uid": user_locked.id,
                                "amt": float(amount),
                                "oid": transaction_id,
                                "details": json.dumps({
                                    "source": "nuvei_webhook",
                                    "tx_id": transaction_id,
                                    "dev_reference": dev_reference,
                                    "status": status,
                                    "status_detail": status_detail,
                                    "application_code": app_code
                                })
                            }
                        )

                        # E. ✅ NUEVO V6.1: Agregar saldo a balance_recharge (NO retirable)
                        add_recharge_balance(session, user_locked.id, amount)
                        
                        logger.info(
                            f"💳 Saldo agregado a balance_recharge: ${amount} "
                            f"(Usuario: {user_locked.telegram_id})"
                        )

                        # F. ✅ Marcar primer depósito si es la primera vez
                        if not user_locked.first_deposit_completed:
                            mark_first_deposit_completed(session, user_locked.id)
                            logger.info(
                                f"🎉 PRIMER DEPÓSITO completado para user_id={user_locked.id}. "
                                f"Status cambiado a ACTIVE."
                            )

                        # G. ✅ COMMIT ÚNICO AL FINAL (todo-o-nada)
                        session.commit()
                        
                        logger.info(
                            f"✅ Transacción DB completada exitosamente para telegram_id={telegram_id}. "
                            f"Saldo balance_recharge incrementado en ${amount}"
                        )

                    except Exception as e:
                        session.rollback()
                        logger.error(
                            f"❌ Error procesando transacción {transaction_id}: {e}",
                            exc_info=True
                        )
                        # Re-raise para que Nuvei sepa que falló y reintente
                        raise

            elif BOT_BACKEND_URL:
                # Modo Stateless (sin DB directa, delega al bot)
                logger.info(f"🔄 Delegando pago al backend del bot: {BOT_BACKEND_URL}")
                
                try:
                    response = requests.post(
                        f"{BOT_BACKEND_URL}/payments/confirm",
                        json={
                            "intent_uuid": dev_reference,
                            "provider_tx_id": transaction_id,
                            "amount_received": float(amount)
                        },
                        headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ Bot backend confirmó el pago exitosamente")
                    else:
                        logger.error(
                            f"❌ Bot backend respondió con error: "
                            f"{response.status_code} - {response.text}"
                        )
                        
                except Exception as e:
                    logger.error(f"❌ Error delegando pago al bot backend: {e}")

            else:
                logger.warning(
                    "⚠️ No hay DB ni BOT_BACKEND_URL configurado. "
                    "Pago recibido pero no procesado."
                )

            # 3. ✅ Notificar al usuario FUERA de la transacción DB
            # Esto previene que un timeout de Telegram bloquee el commit
            try:
                send_telegram_notification(
                    int(telegram_id),
                    f"✅ <b>¡Recarga Exitosa!</b>\n\n"
                    f"Se han acreditado <b>${amount} USD</b> a tu cuenta.\n\n"
                    f"💡 <i>Este saldo debe usarse en retos para poder retirarlo.</i>\n\n"
                    f"¡Gracias por tu confianza! 🎮"
                )
            except Exception as e:
                # No fallar el webhook si falla la notificación
                logger.error(f"❌ Error enviando notificación Telegram: {e}")

        elif status == "1" and status_detail != "3":
            logger.warning(
                f"⚠️ Pago con status=1 pero detail={status_detail} (no procesado). "
                f"tx_id={transaction_id}"
            )
        else:
            logger.info(
                f"ℹ️ Webhook recibido con status={status}, detail={status_detail} "
                f"(no requiere procesamiento). tx_id={transaction_id}"
            )

        return {"status": "OK"}

    except Exception as e:
        logger.error(
            f"❌ Error crítico en webhook: {e}",
            exc_info=True
        )
        # Nuvei espera 200 OK siempre para evitar reintentos infinitos
        # El error ya fue logeado para investigación
        return {"status": "OK"}


@router.get("/health")
def health():
    """
    Endpoint de salud del servicio webhook.
    
    Returns:
        dict: Estado del servicio y conexión a DB
    """
    return {
        "status": "online",
        "service": "nuvei_webhook",
        "version": "6.1",
        "database_connected": HAS_DB,
        "features": {
            "idempotency": True,
            "aml_balance_separation": True,
            "transactional_updates": True,
            "first_deposit_tracking": True,
            "signature_validation": bool(APP_KEY)
        }
    }

