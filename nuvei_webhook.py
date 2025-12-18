# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v6.0 — 100% V6-Compliant + Producción-Ready
# ============================================================

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import hashlib
import logging
import os
import requests
from datetime import datetime
from decimal import Decimal

from database.session import get_db
from database.services import payments_service
from database.crud import payments_crud, user_crud
from database.models.payment_intents import PaymentIntentStatus

router = APIRouter(tags=["Nuvei"])
logger = logging.getLogger(__name__)

# ============================================================
# VARIABLES DE ENTORNO
# ============================================================
APP_KEY = os.getenv("NUVEI_APP_KEY_SERVER")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not APP_KEY:
    logger.critical("❌ NUVEI_APP_KEY_SERVER no configurado")
    raise RuntimeError("NUVEI_APP_KEY_SERVER es obligatorio")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones desactivadas")


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
    Genera stoken según documentación Nuvei.
    
    Formula: MD5([transaction_id]_[application_code]_[user_id]_[app_key])
    
    Example:
        transaction_id = "123"
        app_code = "HF"
        user_id = "123456"
        app_key = "2GYx7SdjmbucLKE924JVFcmCl8t6nB"
        
        for_md5 = "123_HF_123456_2GYx7SdjmbucLKE924JVFcmCl8t6nB"
        stoken = "e242e78ae5f1ed162966f0eacaa0af01"
    
    Args:
        transaction_id: ID de transacción Nuvei
        application_code: Código de aplicación configurado en Nuvei
        user_id: Telegram ID del usuario
        app_key: Clave secreta del servidor
    
    Returns:
        MD5 hash en hexadecimal (32 caracteres)
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    stoken = hashlib.md5(raw.encode()).hexdigest()
    
    logger.debug(f"🔑 STOKEN generado: {raw[:50]}... → {stoken[:8]}...")
    return stoken


# ============================================================
# ENVÍO A TELEGRAM
# ============================================================
def send_telegram_message(chat_id: int, text: str) -> bool:
    """
    Envía mensaje de notificación al usuario vía Telegram.
    
    Args:
        chat_id: Telegram chat ID del usuario
        text: Mensaje en formato HTML
    
    Returns:
        True si se envió exitosamente, False en caso contrario
    
    Note:
        - Falla silenciosamente si BOT_TOKEN no está configurado
        - Timeout de 10 segundos
        - NO afecta el flujo financiero
    """
    if not BOT_TOKEN:
        logger.debug("⚠️ BOT_TOKEN no configurado, saltando notificación")
        return False
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            logger.info(f"📱 Notificación enviada a Telegram ID: {chat_id}")
            return True
        else:
            logger.error(
                f"❌ Telegram error {response.status_code}: {response.text[:100]}"
            )
            return False
            
    except Exception as e:
        logger.error(f"❌ Error enviando a Telegram: {e}")
        return False


# ============================================================
# WEBHOOK NUVEI (V6 - SOLO ORQUESTACIÓN)
# ============================================================
@router.post("/callback")
async def nuvei_callback(
    request: Request,
    session: Session = Depends(get_db)
):
    """
    V6: Webhook de Nuvei (POST callback)
    
    RESPONSABILIDADES V6:
    - Validar STOKEN
    - Parsear payload
    - Delegar a payments_service.confirm_payment()
    - Notificar usuario
    
    NO HACE:
    - ❌ Tocar balances directamente
    - ❌ Crear transacciones manualmente
    - ❌ SQL directo
    - ❌ Lógica de negocio
    - ❌ session.commit() (lo hace el handler/middleware)
    
    Documentación Nuvei:
    - Status 1 + Detail 3 = Aprobado
    - Status 2 = Cancelado
    - Status 4 = Rechazado
    - Status 5 = Expirado
    
    Returns:
        200: Webhook procesado correctamente
        203: STOKEN inválido (seguridad)
    
    Note:
        - Idempotente (Nuvei reintenta si no hay 200)
        - Commit manejado por FastAPI middleware/dependency
        - NUNCA usa lazy loading (DetachedInstanceError)
    """
    try:
        # ============================================================
        # 1️⃣ PARSEAR PAYLOAD
        # ============================================================
        payload = await request.json()
        logger.info(f"📥 Webhook Nuvei recibido: {payload}")
        
        tx = payload.get("transaction", {})
        
        if not tx:
            logger.warning("⚠️ Payload sin campo 'transaction'")
            return {"status": "OK"}
        
        # Extraer campos obligatorios
        transaction_id = tx.get("id")
        status = str(tx.get("status", ""))
        status_detail = str(tx.get("status_detail", ""))
        dev_reference = tx.get("dev_reference")  # Este es nuestro intent.uuid
        application_code = tx.get("application_code")
        amount_str = tx.get("amount")
        authorization_code = tx.get("authorization_code", "N/A")
        
        logger.info(
            f"🔍 Datos webhook:\n"
            f"  - transaction_id: {transaction_id}\n"
            f"  - dev_reference (uuid): {dev_reference}\n"
            f"  - application_code: {application_code}\n"
            f"  - status: {status}/{status_detail}\n"
            f"  - amount: {amount_str}"
        )
        
        # Validar campos obligatorios
        if not all([transaction_id, dev_reference, application_code, amount_str]):
            logger.warning("⚠️ Webhook incompleto, campos obligatorios faltantes")
            return {"status": "OK"}
        
        # Convertir amount a Decimal
        try:
            amount = Decimal(str(amount_str))
        except Exception as e:
            logger.error(f"❌ Amount inválido '{amount_str}': {e}")
            return {"status": "OK"}
        
        # ============================================================
        # 2️⃣ OBTENER PAYMENT INTENT (sin lazy loading)
        # ============================================================
        intent = payments_crud.get_by_uuid(dev_reference, session=session)
        if not intent:
            logger.error(f"❌ PaymentIntent UUID {dev_reference} no existe")
            return {"status": "OK"}
        
        # V6: Cargar usuario EXPLÍCITAMENTE (no lazy loading)
        user = user_crud.get_user_by_id(intent.user_id, session=session)
        if not user:
            logger.error(f"❌ Usuario {intent.user_id} no encontrado")
            return {"status": "OK"}
        
        telegram_id = user.telegram_id
        
        # ============================================================
        # 3️⃣ VALIDAR STOKEN (SEGURIDAD)
        # ============================================================
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),  # Telegram ID desde BD
            app_key=APP_KEY
        )
        
        logger.info(
            f"🔑 STOKEN validación:\n"
            f"   Recibido: {sent_stoken}\n"
            f"   Esperado: {expected_stoken}"
        )
        
        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN INVÁLIDO - Posible ataque")
            raise HTTPException(status_code=203, detail="Token error")
        
        logger.info("✅ STOKEN válido")
        
        # ============================================================
        # 4️⃣ VALIDAR MONTO (SEGURIDAD)
        # ============================================================
        if abs(intent.amount - amount) > Decimal("0.01"):
            logger.error(
                f"❌ Monto no coincide:\n"
                f"   BD: ${intent.amount}\n"
                f"   Webhook: ${amount}"
            )
            return {"status": "OK"}
        
        # ============================================================
        # 5️⃣ PROCESAR SEGÚN ESTADO
        # ============================================================
        
        # CASO 1: PAGO APROBADO
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 PAGO APROBADO | UUID {dev_reference} | ${amount}")
            
            try:
                # ============================================================
                # V6: DELEGACIÓN TOTAL A SERVICE
                # ============================================================
                result = payments_service.confirm_payment(
                    intent_uuid=dev_reference,
                    amount_received=amount,
                    session=session
                )
                
                # Actualizar provider_intent_id con transaction_id de Nuvei
                payments_crud.update_provider_intent_id(
                    intent=intent,
                    provider_intent_id=transaction_id,
                    session=session
                )
                
                # V6: NO commit aquí - lo maneja el handler/middleware
                session.flush()
                
                logger.info(
                    f"✅ Pago confirmado exitosamente:\n"
                    f"   UUID: {dev_reference}\n"
                    f"   Amount: ${amount}\n"
                    f"   Result: {result}"
                )
                
                # ============================================================
                # NOTIFICAR USUARIO (no afecta transacción)
                # ============================================================
                voucher = (
                    "🎉 <b>PAGO APROBADO</b>\n\n"
                    f"💳 <b>Monto:</b> ${amount}\n"
                    f"🧾 <b>Transacción:</b> {transaction_id}\n"
                    f"🔐 <b>Autorización:</b> {authorization_code}\n"
                    f"🏷 <b>Referencia:</b> {dev_reference}\n\n"
                    "✅ Tu saldo ha sido actualizado\n\n"
                    "Gracias por usar <b>PITIUPI</b> 🚀"
                )
                send_telegram_message(telegram_id, voucher)
                
            except ValueError as e:
                # Idempotencia: si ya estaba completado
                error_str = str(e).lower()
                if "already_completed" in error_str or "ignored" in error_str:
                    logger.info(f"🔁 PaymentIntent {dev_reference} ya estaba completado")
                    return {"status": "OK"}
                else:
                    logger.error(f"❌ Error confirmando pago: {e}")
                    raise  # Re-raise para que FastAPI maneje rollback
            
            except Exception as e:
                logger.error(f"❌ Error procesando pago aprobado: {e}", exc_info=True)
                raise  # Re-raise para rollback automático
        
        # CASO 2: PAGO CANCELADO
        elif status == "2":
            logger.info(f"🟡 PAGO CANCELADO | UUID {dev_reference}")
            
            # V6: Usar enum, NO string
            intent.status = PaymentIntentStatus.CANCELLED
            session.flush()
            
            # Notificar usuario
            message = (
                "❌ <b>PAGO CANCELADO</b>\n\n"
                f"🧾 <b>Referencia:</b> {dev_reference}\n"
                f"💳 <b>Monto:</b> ${amount}\n\n"
                "El pago no se completó. Puedes intentar nuevamente."
            )
            send_telegram_message(telegram_id, message)
        
        # CASO 3: PAGO RECHAZADO
        elif status == "4":
            logger.info(f"🔴 PAGO RECHAZADO | UUID {dev_reference}")
            
            # V6: Usar enum, NO string
            intent.status = PaymentIntentStatus.REJECTED
            session.flush()
            
            message = (
                "⚠️ <b>PAGO RECHAZADO</b>\n\n"
                f"🧾 <b>Referencia:</b> {dev_reference}\n"
                f"💳 <b>Monto:</b> ${amount}\n"
                f"📝 <b>Motivo:</b> {tx.get('message', 'Rechazado por procesador')}\n\n"
                "Por favor verifica tus datos e intenta nuevamente."
            )
            send_telegram_message(telegram_id, message)
        
        # CASO 4: PAGO EXPIRADO
        elif status == "5":
            logger.info(f"⏰ PAGO EXPIRADO | UUID {dev_reference}")
            
            intent.status = PaymentIntentStatus.EXPIRED
            session.flush()
            
            message = (
                "⏰ <b>PAGO EXPIRADO</b>\n\n"
                f"🧾 <b>Referencia:</b> {dev_reference}\n"
                f"💳 <b>Monto:</b> ${amount}\n\n"
                "El enlace de pago ha expirado. Genera uno nuevo."
            )
            send_telegram_message(telegram_id, message)
        
        # CASO 5: OTROS ESTADOS
        else:
            logger.info(
                f"ℹ️ Estado no procesado: {status}/{status_detail} | UUID {dev_reference}"
            )
        
        return {"status": "OK"}
        
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Error crítico en webhook: {e}", exc_info=True)
        raise  # Re-raise para que FastAPI/middleware maneje rollback


# ============================================================
# ENDPOINT DE SALUD
# ============================================================
@router.get("/health")
async def health_check():
    """
    V6: Health check del servicio de webhook.
    
    Returns:
        Estado del servicio y configuración
    """
    return {
        "status": "healthy",
        "service": "nuvei_webhook",
        "version": "6.0",
        "app_key_configured": bool(APP_KEY),
        "bot_configured": bool(BOT_TOKEN),
        "timestamp": datetime.now().isoformat()
    }
