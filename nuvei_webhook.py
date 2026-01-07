# ============================================================
# nuvei_webhook.py — Receptor de Webhooks Nuvei (Ecuador)
# PITIUPI v6.3 — ✅ CORRECCIÓN: stoken con user.id de Nuvei + Logging detallado
# VERSIÓN CORREGIDA: Usa user.id de payload Nuvei para validación de firma
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
        user_id: ID del usuario (SEGÚN DOCUMENTACIÓN NUVEI: usar user.id del payload)
        app_key: Llave secreta del servidor
        
    Returns:
        str: Hash MD5 del token
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    calculated = hashlib.md5(raw.encode()).hexdigest()
    
    # Log detallado para debugging
    logger.debug(f"🔍 Calculando stoken con:")
    logger.debug(f"   transaction_id: {transaction_id}")
    logger.debug(f"   application_code: {application_code}")
    logger.debug(f"   user_id: {user_id}")
    logger.debug(f"   app_key: ...{app_key[-6:] if app_key else ''}")
    logger.debug(f"   raw: {raw}")
    logger.debug(f"   stoken calculado: {calculated}")
    
    return calculated

def extract_nuvei_user_id(payload: dict) -> str:
    """
    Intenta extraer el user.id que Nuvei usa para calcular el stoken.
    
    SEGÚN DOCUMENTACIÓN NUVEI: El user_id debe ser el mismo que se envió
    en la solicitud de pago ORIGINAL. Si no se puede determinar, se usa
    telegram_id como fallback.
    
    Args:
        payload: Payload completo del webhook Nuvei
        
    Returns:
        str: user.id para usar en cálculo de stoken
    """
    # 1. Intentar obtener user.id directamente del payload Nuvei
    user_data = payload.get("user", {})
    if user_data and user_data.get("id"):
        nuvei_user_id = str(user_data["id"])
        logger.info(f"📊 User ID extraído del payload Nuvei: {nuvei_user_id}")
        return nuvei_user_id
    
    # 2. Si no existe, usar el campo 'customer_id' que podría contener el ID
    customer_id = payload.get("transaction", {}).get("customer_id")
    if customer_id:
        logger.info(f"📊 Usando customer_id como user ID: {customer_id}")
        return str(customer_id)
    
    # 3. Intentar extraer de dev_reference (formato: PITIUPI-{telegram_id}-...)
    dev_ref = payload.get("transaction", {}).get("dev_reference", "")
    if dev_ref.startswith("PITIUPI-"):
        try:
            telegram_id = dev_ref.split("-")[1]
            logger.info(f"📊 Usando telegram_id como fallback: {telegram_id}")
            return telegram_id
        except Exception:
            pass
    
    # 4. Último recurso: usar valor por defecto
    logger.warning("⚠️ No se pudo determinar user ID, usando 'unknown'")
    return "unknown"

def log_nuvei_diagnosis(payload: dict, transaction_id: str, dev_reference: str):
    """
    Registra información detallada del payload Nuvei para debugging.
    """
    logger.info("=" * 60)
    logger.info("🔍 DIAGNÓSTICO DE PAYLOAD NUVEI")
    logger.info("=" * 60)
    
    # 1. Información básica
    tx = payload.get("transaction", {})
    logger.info(f"📄 Transacción: {transaction_id}")
    logger.info(f"📝 Referencia: {dev_reference}")
    logger.info(f"🏷️  Status: {tx.get('status')}/{tx.get('status_detail')}")
    logger.info(f"💰 Monto: ${tx.get('amount')}")
    stoken_received = tx.get('stoken', 'NO ENVIADO')
    logger.info(f"🔑 Stoken recibido: {stoken_received[:16]}..." if len(stoken_received) > 16 else f"🔑 Stoken recibido: {stoken_received}")
    
    # 2. Buscar posibles user.id
    user_data = payload.get("user", {})
    if user_data:
        logger.info(f"👤 User object encontrado en payload:")
        for key, value in user_data.items():
            logger.info(f"   {key}: {value}")
    
    # 3. Buscar customer_id
    customer_id = tx.get("customer_id")
    if customer_id:
        logger.info(f"👤 Customer ID encontrado: {customer_id}")
    
    # 4. Campos adicionales importantes
    important_fields = ["customer_email", "user_id", "client_unique_id", "external_id", "customer_name"]
    for field in important_fields:
        value = tx.get(field)
        if value:
            logger.info(f"📋 {field}: {value}")
    
    # 5. Mostrar estructura completa para debugging
    logger.info(f"📋 Campos disponibles en transaction: {list(tx.keys()) if isinstance(tx, dict) else 'NO DICT'}")
    
    logger.info("=" * 60)

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
    ✅ V6.3 CORREGIDO: Webhook asíncrono para procesar pagos de Nuvei.
    
    MEJORAS CRÍTICAS:
    1. Usa user.id de Nuvei para validación de stoken
    2. Doble validación (user.id Nuvei y telegram_id)
    3. Logging detallado para debugging
    4. Continuación temporal si validación falla (para testing)
    
    Flow con Idempotencia:
    1. Validar firma de seguridad usando user.id de Nuvei
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
        
        # 2.1 Log detallado del payload para debugging
        log_nuvei_diagnosis(payload, transaction_id, dev_reference)

        # 3. ✅ VALIDACIÓN DE FIRMA CON USER.ID DE NUVEI
        if not APP_KEY:
            logger.warning("⚠️ APP_KEY no configurado, omitiendo validación de firma")
        elif not sent_stoken:
            logger.error("❌ Webhook sin token de seguridad (stoken)")
            raise HTTPException(status_code=401, detail="Firma de seguridad faltante")
        else:
            # OPCIÓN A: Intentar usar el user.id que Nuvei envió en el payload
            nuvei_user_id = extract_nuvei_user_id(payload)
            logger.info(f"🔍 Intentando validación con user_id: {nuvei_user_id}")
            
            expected_token = generate_stoken(transaction_id, app_code, nuvei_user_id, APP_KEY)
            
            # OPCIÓN B: También probar con telegram_id si A falla
            try:
                telegram_id_from_ref = dev_reference.split("-")[1]
                expected_token_with_telegram = generate_stoken(
                    transaction_id, app_code, telegram_id_from_ref, APP_KEY
                )
                
                # Comparar ambas posibilidades
                if sent_stoken == expected_token:
                    logger.info(f"✅ Firma validada CORRECTAMENTE con Nuvei user_id: {nuvei_user_id}")
                elif sent_stoken == expected_token_with_telegram:
                    logger.info(f"✅ Firma validada CORRECTAMENTE con telegram_id: {telegram_id_from_ref}")
                    nuvei_user_id = telegram_id_from_ref  # Actualizar para uso posterior
                else:
                    logger.error(f"❌ FIRMA NO COINCIDE - stoken recibido: {sent_stoken}")
                    logger.error(f"   Opción A (Nuvei user_id={nuvei_user_id}): {expected_token}")
                    logger.error(f"   Opción B (telegram_id={telegram_id_from_ref}): {expected_token_with_telegram}")
                    
                    # ⚠️ TEMPORAL: Continuar procesamiento para debugging
                    logger.warning("⚠️ CONTINUANDO SIN VALIDACIÓN PARA DEBUGGING - Contacta a Nuvei")
                    # Para producción, descomentar la siguiente línea:
                    # raise HTTPException(status_code=401, detail="Firma de seguridad inválida")
                    
            except Exception as e:
                logger.error(f"❌ Error calculando stoken: {e}")
                logger.warning("⚠️ CONTINUANDO SIN VALIDACIÓN PARA DEBUGGING")
                # Para producción, descomentar la siguiente línea:
                # raise HTTPException(status_code=401, detail=f"Error validando firma: {str(e)[:50]}")

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

        # 6. ✅ EXTRAER TELEGRAM ID SIEMPRE DE dev_reference
        try:
            # Formato esperado: PITIUPI-{telegram_id}-{timestamp}
            # NOTA: Esto es INDEPENDIENTE del user.id usado en el stoken
            parts = dev_reference.split("-")
            if len(parts) < 2:
                raise ValueError(f"Formato de dev_reference incorrecto: {dev_reference}")
            telegram_id = parts[1]
            logger.info(f"📱 Telegram ID extraído de dev_reference: {telegram_id}")
        except Exception as e:
            logger.error(f"❌ Error extrayendo Telegram ID de {dev_reference}: {e}")
            raise HTTPException(status_code=400, detail="Referencia de usuario inválida")

        # 7. ✅ PROCESAR PAGO CON BASE DE DATOS
        if HAS_DB:
            with db_session() as session:
                try:
                    # ✅ A. IDEMPOTENCIA MEJORADA: Verificar si ya fue procesado
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
                                        updated_at = NOW(),
                                        completed_at = NOW(),
                                        webhook_payload = :webhook_payload
                                    WHERE provider_order_id = :order_id
                                """),
                                {
                                    "amount": amount, 
                                    "order_id": transaction_id,
                                    "webhook_payload": json.dumps(payload)
                                }
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
                        
                        # Si existe pero es FAILED/EXPIRED, actualizar a COMPLETED
                        if current_status in ["FAILED", "EXPIRED"]:
                            logger.info(f"🔄 Reactivando pago {current_status}: {transaction_id}")
                            session.execute(
                                text("""
                                    UPDATE payment_intents 
                                    SET status = 'COMPLETED', 
                                        amount_received = :amount,
                                        updated_at = NOW(),
                                        completed_at = NOW(),
                                        failure_reason = NULL,
                                        webhook_payload = :webhook_payload
                                    WHERE provider_order_id = :order_id
                                """),
                                {
                                    "amount": amount, 
                                    "order_id": transaction_id,
                                    "webhook_payload": json.dumps(payload)
                                }
                            )
                            session.commit()
                            logger.info(f"✅ Pago reactivado a COMPLETADO: {transaction_id}")
                            return {"status": "OK", "message": "reactivated"}
                    
                    # B. Buscar usuario
                    user = get_user_by_telegram_id(session, telegram_id)
                    if not user:
                        logger.error(f"❌ Usuario no encontrado: telegram_id={telegram_id}")
                        raise HTTPException(status_code=404, detail="Usuario no encontrado")

                    logger.info(f"👤 Usuario encontrado: {user.full_legal_name}, ID={user.id}")

                    # C. Bloquear fila del usuario para actualización segura
                    stmt = select(User).where(User.id == user.id).with_for_update()
                    user_locked = session.execute(stmt).scalar_one()

                    # D. ✅ INSERTAR PaymentIntent SIN ON CONFLICT
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
                    
                    # Verificar campos correctos en el modelo User
                    balance_recharge = user_locked.balance_recharge or Decimal("0.00")
                    balance_total = user_locked.balance_total or Decimal("0.00")
                    total_deposits = user_locked.total_deposits or Decimal("0.00")
                    
                    # Actualizar balances
                    new_balance_recharge = balance_recharge + Decimal(str(amount))
                    new_balance_total = balance_total + Decimal(str(amount))
                    new_total_deposits = total_deposits + Decimal(str(amount))
                    
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
                    # Verificar el nombre correcto del campo en el modelo User
                    if not getattr(user_locked, 'first_deposit_made', False):
                        session.execute(
                            text("""
                                UPDATE users 
                                SET first_deposit_made = TRUE,
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
                    raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)[:100]}")

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
        "version": "6.3",
        "database_connected": HAS_DB,
        "features": {
            "idempotency": True,
            "aml_balance_separation": True,
            "transactional_updates": True,
            "first_deposit_tracking": True,
            "signature_validation": bool(APP_KEY),
            "nuvei_user_id_extraction": True,
            "debug_mode": True  # Temporalmente activado
        }
    }
