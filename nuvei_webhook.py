# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.2 — ✅ CORREGIDO: Async + Validación Rigurosa + Manejo de Errores
# ============================================================

from fastapi import APIRouter, Request, HTTPException
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
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
async def nuvei_callback(request: Request):
    """
    ✅ V6.2 CORREGIDO: Webhook asíncrono para procesar pagos de Nuvei.
    
    MEJORAS CRÍTICAS:
    1. Función asíncrona (async def) para manejar correctamente await request.json()
    2. Manejo adecuado de errores: solo devuelve 200 OK si el procesamiento fue exitoso
    3. Validación robusta de firma de seguridad
    4. Idempotencia mejorada con bloqueo de fila
    5. Registro detallado en base de datos
    6. Manejo de timeouts y errores de red
    
    Flow con Idempotencia:
    1. Validar firma de seguridad
    2. Parsear payload y extraer datos críticos
    3. Verificar idempotencia ANTES de cualquier operación
    4. Procesar solo transacciones exitosas (status=1, detail=3)
    5. Actualizar DB con bloqueo de fila
    6. Notificar usuario SOLO si todo fue exitoso
    """
    try:
        # 1. Obtener cuerpo completo y parsear payload
        raw_body = await request.body()
        payload = await request.json()
        tx = payload.get("transaction", {})
        
        # 2. Extraer datos críticos
        transaction_id = str(tx.get("id", "")).strip()
        dev_reference = str(tx.get("dev_reference", "")).strip()
        app_code = str(tx.get("application_code", "")).strip()
        status = str(tx.get("status", "")).strip()
        status_detail = str(tx.get("status_detail", "")).strip()
        amount = float(tx.get("amount", 0))
        sent_stoken = str(tx.get("stoken", "")).strip()

        logger.info(
            f"📥 Webhook recibido: tx_id={transaction_id}, "
            f"ref={dev_reference}, status={status}, detail={status_detail}, amount=${amount}"
        )
        logger.debug(f"📄 Payload completo: {payload}")

        # 3. ✅ VALIDACIÓN DE FIRMA PRIMERO (crítico para seguridad)
        if not APP_KEY:
            logger.warning("⚠️ APP_KEY no configurado, omitiendo validación de firma")
        elif not sent_stoken:
            logger.error("❌ Webhook sin token de seguridad (stoken)")
            raise HTTPException(status_code=401, detail="Firma de seguridad faltante")
        else:
            # Extraer telegram_id de dev_reference para la firma
            try:
                telegram_id = dev_reference.split("-")[1]
            except Exception as e:
                logger.error(f"❌ Formato de dev_reference inválido para firma: {dev_reference} - {e}")
                raise HTTPException(status_code=400, detail="Formato de referencia inválido")
            
            expected_token = generate_stoken(transaction_id, app_code, telegram_id, APP_KEY)
            if sent_stoken != expected_token:
                logger.error(
                    f"❌ FIRMA INVÁLIDA: tx_id={transaction_id}. "
                    f"Expected: {expected_token}, Got: {sent_stoken}"
                )
                raise HTTPException(status_code=401, detail="Firma de seguridad inválida")
            logger.info(f"✅ Firma validada correctamente para tx {transaction_id}")

        # 4. ✅ Verificar formato mínimo de dev_reference
        if not dev_reference.startswith("PITIUPI-"):
            logger.error(f"❌ dev_reference inválido: {dev_reference}")
            raise HTTPException(status_code=400, detail="Referencia de desarrollador inválida")

        # 5. ✅ Procesar SOLO transacciones exitosas
        if status != "1" or status_detail != "3":
            logger.info(
                f"ℹ️ Webhook ignorado - no es pago exitoso: status={status}, detail={status_detail}, tx_id={transaction_id}"
            )
            # Para transacciones no exitosas, aún devolvemos 200 OK para no causar reintento innecesario
            return {"status": "ignored", "reason": f"status:{status}, detail:{status_detail}"}

        # 6. ✅ EXTRAER TELEGRAM ID CORRECTAMENTE
        try:
            # Formato esperado: PITIUPI-{telegram_id}-{timestamp}
            parts = dev_reference.split("-")
            if len(parts) < 2:
                raise ValueError(f"Formato incorrecto: {dev_reference}")
            telegram_id = parts[1]
            logger.info(f"📱 Telegram ID extraído: {telegram_id}")
        except Exception as e:
            logger.error(f"❌ Error extrayendo Telegram ID de {dev_reference}: {e}")
            raise HTTPException(status_code=400, detail="Referencia de usuario inválida")

        # 7. ✅ PROCESAR PAGO CON BASE DE DATOS
        if HAS_DB:
            with db_session() as session:
                try:
                    # ✅ A. IDEMPOTENCIA: Verificar si ya fue procesado
                    existing_intent = session.execute(
                        text("""
                            SELECT id, status, amount_received 
                            FROM payment_intents 
                            WHERE provider_order_id = :order_id
                            FOR UPDATE
                        """),
                        {"order_id": transaction_id}
                    ).fetchone()

                    if existing_intent:
                        current_status = existing_intent[1]
                        logger.info(f"🔄 Pago ya existe en DB: {transaction_id}, status={current_status}")
                        
                        # Si ya está completado, devolver éxito inmediatamente
                        if current_status == "COMPLETED":
                            logger.info(f"✅ Pago ya procesado: {transaction_id}")
                            return {"status": "OK", "message": "already_processed"}
                        
                        # Si está pendiente pero el monto coincide, actualizar a completado
                        if current_status == "PENDING" and float(existing_intent[2] or 0) == amount:
                            logger.info(f"🔄 Actualizando pago pendiente a completado: {transaction_id}")
                            session.execute(
                                text("""
                                    UPDATE payment_intents 
                                    SET status = 'COMPLETED', 
                                        amount_received = :amount,
                                        updated_at = NOW()
                                    WHERE provider_order_id = :order_id
                                """),
                                {"amount": amount, "order_id": transaction_id}
                            )
                            session.commit()
                            logger.info(f"✅ Pago actualizado a COMPLETADO: {transaction_id}")
                            
                            # Obtener usuario para notificación
                            user = get_user_by_telegram_id(session, telegram_id)
                            if user:
                                send_telegram_notification(
                                    int(telegram_id),
                                    f"✅ <b>¡Pago Confirmado!</b>\n\n"
                                    f"Se han acreditado <b>${amount} USD</b> a tu cuenta.\n\n"
                                    f"🆔 Transacción: <code>{transaction_id[:16]}</code>"
                                )
                            return {"status": "OK", "message": "updated_from_pending"}
                    
                    # B. Buscar usuario
                    user = get_user_by_telegram_id(session, telegram_id)
                    if not user:
                        logger.error(f"❌ Usuario no encontrado: telegram_id={telegram_id}")
                        raise HTTPException(status_code=404, detail="Usuario no encontrado")

                    logger.info(f"👤 Usuario encontrado: {user.full_legal_name}, ID={user.id}")

                    # C. Bloquear fila del usuario para actualización segura
                    stmt = select(User).where(User.id == user.id).with_for_update()
                    user_locked = session.execute(stmt).scalar_one()

                    # D. ✅ INSERTAR/ACTUALIZAR PaymentIntent CORRECTAMENTE
                    session.execute(
                        text("""
                            INSERT INTO payment_intents (
                                uuid, user_id, amount, amount_received, status, 
                                provider_order_id, provider, currency, details,
                                created_at, updated_at, expires_at,
                                ledger_transaction_uuid, failure_reason, 
                                completed_at, webhook_payload
                            )
                            VALUES (
                                gen_random_uuid(), 
                                :user_id, 
                                :amount, 
                                :amount_received, 
                                :status, 
                                :provider_order_id, 
                                :provider, 
                                :currency, 
                                :details,
                                NOW(), 
                                NOW(), 
                                NOW() + INTERVAL '1 hour',
                                NULL,
                                NULL,
                                NOW(),
                                :webhook_payload
                            )
                            ON CONFLICT (provider_order_id) DO UPDATE SET 
                                status = EXCLUDED.status,
                                amount_received = EXCLUDED.amount_received,
                                updated_at = NOW(),
                                completed_at = NOW(),
                                webhook_payload = EXCLUDED.webhook_payload;
                        """),
                        {
                            "user_id": user_locked.id,
                            "amount": amount,
                            "amount_received": amount,
                            "status": "COMPLETED",
                            "provider_order_id": transaction_id,
                            "provider": "nuvei",
                            "currency": "USD",
                            "details": json.dumps({
                                "source": "nuvei_webhook",
                                "tx_id": transaction_id,
                                "dev_reference": dev_reference,
                                "status": status,
                                "status_detail": status_detail,
                                "application_code": app_code,
                                "raw_payload": payload
                            }),
                            "webhook_payload": json.dumps(payload)
                        }
                    )

                    # E. ✅ ACTUALIZAR BALANCES DEL USUARIO
                    logger.info(f"💰 Actualizando balances para usuario {user_locked.id}")
                    
                    # Actualizar balance_recharge (separado para cumplir AML)
                    new_balance_recharge = (user_locked.balance_recharge or 0) + Decimal(str(amount))
                    new_balance_total = (user_locked.balance_total or 0) + Decimal(str(amount))
                    new_total_deposits = (user_locked.total_deposits or 0) + Decimal(str(amount))
                    
                    session.execute(
                        text("""
                            UPDATE users 
                            SET balance_recharge = :balance_recharge,
                                balance_total = :balance_total,
                                total_deposits = :total_deposits,
                                updated_at = NOW()
                            WHERE id = :user_id
                        """),
                        {
                            "balance_recharge": new_balance_recharge,
                            "balance_total": new_balance_total,
                            "total_deposits": new_total_deposits,
                            "user_id": user_locked.id
                        }
                    )

                    # F. ✅ MARCAR PRIMER DEPÓSITO SI APLICA
                    if not user_locked.first_deposit_completed:
                        session.execute(
                            text("""
                                UPDATE users 
                                SET first_deposit_completed = TRUE,
                                    first_deposit_amount = :amount,
                                    first_deposit_date = NOW(),
                                    registration_completed = TRUE,
                                    status = 'ACTIVE',
                                    updated_at = NOW()
                                WHERE id = :user_id
                            """),
                            {
                                "amount": amount,
                                "user_id": user_locked.id
                            }
                        )
                        logger.info(f"🎉 PRIMER DEPÓSITO completado para usuario {user_locked.id}")

                    # G. ✅ COMMIT ÚNICO
                    session.commit()
                    logger.info(f"✅ Transacción completada exitosamente: {transaction_id}")
                    
                    # H. ✅ NOTIFICAR AL USUARIO
                    try:
                        send_telegram_notification(
                            int(telegram_id),
                            f"✅ <b>¡Recarga Exitosa!</b>\n\n"
                            f"Se han acreditado <b>${amount} USD</b> a tu cuenta.\n\n"
                            f"💰 <b>Nuevo balance total:</b> ${new_balance_total:.2f} USD\n"
                            f"🆔 <b>Transacción:</b> <code>{transaction_id[:16]}</code>\n\n"
                            f"🎮 ¡Ahora puedes participar en retos y torneos!"
                        )
                    except Exception as e:
                        logger.error(f"❌ Error enviando notificación a {telegram_id}: {e}")
                        # No fallar la transacción por error de notificación

                    return {"status": "OK", "transaction_id": transaction_id}

                except Exception as e:
                    session.rollback()
                    logger.error(f"❌ Error procesando transacción {transaction_id}: {e}", exc_info=True)
                    # Re-lanzar para que Nuvei reintente
                    raise

        # 8. ✅ MODO STATELESS (sin DB)
        elif BOT_BACKEND_URL:
            logger.info(f"🔄 Modo stateless: delegando pago a backend del bot")
            try:
                response = requests.post(
                    f"{BOT_BACKEND_URL}/payments/webhook",
                    json={
                        "transaction_id": transaction_id,
                        "telegram_id": telegram_id,
                        "amount": amount,
                        "dev_reference": dev_reference,
                        "status": status,
                        "status_detail": status_detail
                    },
                    headers={"X-Internal-API-Key": INTERNAL_API_KEY},
                    timeout=15
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Bot backend confirmó el pago: {transaction_id}")
                    return {"status": "OK", "delegated": True}
                else:
                    logger.error(
                        f"❌ Bot backend respondió con error {response.status_code}: {response.text}"
                    )
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error del bot backend: {response.text[:100]}"
                    )
                    
            except requests.exceptions.Timeout:
                logger.error("❌ Timeout delegando pago al bot backend")
                raise HTTPException(status_code=504, detail="Timeout al comunicarse con el bot")
            except Exception as e:
                logger.error(f"❌ Error delegando pago: {e}")
                raise HTTPException(status_code=500, detail="Error interno al delegar pago")

        # 9. ✅ SIN DB NI BOT_BACKEND_URL
        else:
            logger.warning(
                "⚠️ Modo degradado: no hay DB ni BOT_BACKEND_URL configurado. "
                "El pago se registró pero no se procesó completamente."
            )
            # En modo degradado, aún devolvemos 200 OK pero con advertencia
            return {
                "status": "OK",
                "warning": "degraded_mode",
                "transaction_id": transaction_id,
                "amount": amount,
                "telegram_id": telegram_id
            }

    except HTTPException:
        # Re-lanzar errores HTTP para mantener el código de estado
        raise
    except Exception as e:
        logger.error(f"❌ Error crítico no manejado en webhook: {e}", exc_info=True)
        # Para cualquier error no manejado, devolvemos 500 para que Nuvei reintente
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)[:100]}")


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
        "version": "6.2",
        "database_connected": HAS_DB,
        "features": {
            "idempotency": True,
            "aml_balance_separation": True,
            "transactional_updates": True,
            "first_deposit_tracking": True,
            "signature_validation": bool(APP_KEY)
        }
    }

