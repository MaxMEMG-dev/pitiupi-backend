# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei (PRODUCCIÓN)
# PITIUPI v5.1 — STOKEN CORREGIDO + VALIDACIONES COMPLETAS
# ============================================================

from fastapi import APIRouter, Request, HTTPException
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
    raise RuntimeError("NUVEI_APP_KEY_SERVER no configurado en variables de entorno")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones Telegram desactivadas")


# ============================================================
# STOKEN — FÓRMULA OFICIAL NUVEI
# MD5(transaction_id_application_code_user_id_app_key)
# ============================================================

def generate_stoken(
    transaction_id: str,
    application_code: str,  # application_code del webhook
    user_id: str,           # user.id (string)
    app_key: str            # app_key del servidor
) -> str:
    """
    Genera stoken según documentación oficial Nuvei.
    IMPORTANTE: Usa application_code del webhook, no de las credenciales.
    """
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    stoken = hashlib.md5(raw.encode()).hexdigest()
    
    # Logs de seguridad (ocultamos app_key completa)
    masked_app_key = f"...{app_key[-4:]}" if len(app_key) > 4 else "****"
    logger.info(f"🔑 STOKEN calculado:")
    logger.info(f"   Transaction: {transaction_id}")
    logger.info(f"   App Code: {application_code}")
    logger.info(f"   User ID: {user_id}")
    logger.info(f"   App Key: {masked_app_key}")
    logger.info(f"   Hash MD5: {stoken}")
    
    return stoken


# ============================================================
# ENVÍO DE MENSAJE A TELEGRAM
# ============================================================

def send_telegram_message(chat_id: int, text: str):
    """Envía mensaje al usuario vía bot de Telegram"""
    if not BOT_TOKEN:
        logger.debug("⚠️ BOT_TOKEN no configurado, omitiendo notificación")
        return

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

        if response.status_code != 200:
            logger.error(f"❌ Error Telegram {response.status_code}: {response.text[:100]}")
        else:
            logger.info(f"📱 Notificación enviada a Telegram ID: {chat_id}")

    except Exception as e:
        logger.error(f"❌ Error enviando mensaje Telegram: {e}")


# ============================================================
# WEBHOOK NUVEI - VERSIÓN PRODUCCIÓN
# ============================================================

@router.post("/callback")
async def nuvei_callback(request: Request):
    """
    Webhook oficial Nuvei para procesar transacciones.
    Valida STOKEN, actualiza estado e incrementa balance.
    """
    try:
        payload = await request.json()
        logger.info("📥 [Nuvei Webhook] Recibido")

        tx = payload.get("transaction")
        user = payload.get("user", {})

        if not tx:
            logger.warning("⚠️ Webhook sin objeto transaction")
            return {"status": "OK"}

        # --------------------------------------------------
        # EXTRACCIÓN DE CAMPOS CRÍTICOS
        # --------------------------------------------------
        transaction_id = tx.get("id")
        status = str(tx.get("status"))
        status_detail = str(tx.get("status_detail"))
        intent_id = tx.get("dev_reference")
        application_code = tx.get("application_code")  # ¡CRÍTICO!
        order_id = tx.get("ltp_id")
        authorization_code = tx.get("authorization_code")
        paid_date = tx.get("paid_date")
        amount = float(tx.get("amount", 0))
        telegram_id = user.get("id")  # string

        # Validación de campos obligatorios
        missing_fields = []
        if not transaction_id: missing_fields.append("transaction.id")
        if not intent_id: missing_fields.append("dev_reference")
        if not telegram_id: missing_fields.append("user.id")
        if not application_code: missing_fields.append("application_code")

        if missing_fields:
            logger.warning(f"⚠️ Webhook incompleto, faltan: {missing_fields}")
            return {"status": "OK"}

        # Conversión segura de tipos
        try:
            intent_id_int = int(intent_id)
        except ValueError:
            logger.error(f"❌ dev_reference no es numérico: {intent_id}")
            return {"status": "OK"}

        # Logs de diagnóstico (sin datos sensibles)
        logger.info(f"📋 Datos webhook:")
        logger.info(f"   Intent: {intent_id_int}")
        logger.info(f"   Transaction: {transaction_id}")
        logger.info(f"   App Code: {application_code}")
        logger.info(f"   User ID: {telegram_id}")
        logger.info(f"   Status: {status}/{status_detail}")
        logger.info(f"   Amount: ${amount:.2f}")

        # --------------------------------------------------
        # VALIDACIÓN STOKEN (SEGURIDAD)
        # --------------------------------------------------
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
            app_key=APP_KEY
        )

        logger.info(f"🔍 Validación STOKEN:")
        logger.info(f"   Recibido: {sent_stoken[:8]}...")
        logger.info(f"   Esperado: {expected_stoken[:8]}...")

        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido - posible webhook fraudulento")
            # 203 según documentación Nuvei para token error
            raise HTTPException(status_code=203, detail="Token error")

        logger.info("✅ STOKEN válido - webhook auténtico")

        # --------------------------------------------------
        # OBTENER INTENT DE LA BASE DE DATOS
        # --------------------------------------------------
        intent = get_payment_intent(intent_id_int)
        if not intent:
            logger.error(f"❌ Intent {intent_id_int} no existe en BD")
            return {"status": "OK"}

        # --------------------------------------------------
        # VALIDACIÓN DE MONTO (RECOMENDACIÓN NUVEI)
        # --------------------------------------------------
        intent_amount = float(intent.get("amount", 0))
        if abs(intent_amount - amount) > 0.01:  # Tolerancia de 1 centavo
            logger.error(f"❌ Monto no coincide: BD=${intent_amount:.2f} vs Webhook=${amount:.2f}")
            # No procesamos, pero respondemos OK para no recibir más webhooks
            update_payment_intent(intent_id_int, status="error", message="Monto no coincide")
            return {"status": "OK"}

        # --------------------------------------------------
        # IDEMPOTENCIA: Evitar procesar dos veces
        # --------------------------------------------------
        if intent.get("status") == "paid":
            logger.info(f"🔁 Intent {intent_id_int} ya estaba pagado - idempotencia")
            return {"status": "OK"}

        # --------------------------------------------------
        # ACTUALIZAR order_id SI NO EXISTE
        # --------------------------------------------------
        if order_id and not intent.get("order_id"):
            update_payment_intent(intent_id_int, order_id=order_id)

        # --------------------------------------------------
        # PROCESAR SEGÚN ESTADO
        # --------------------------------------------------
        
        # 🟢 PAGO APROBADO (status=1, status_detail=3)
        if status == "1" and status_detail == "3":
            logger.info(f"🟢 Pago APROBADO → Intent {intent_id_int}")
            
            # 1. Marcar como pagado en BD
            mark_intent_paid(
                intent_id=intent_id_int,
                provider_tx_id=transaction_id,
                status_detail=int(status_detail),
                authorization_code=authorization_code,
                message="Pago aprobado por Nuvei",
            )
            
            # 2. Incrementar balance del usuario
            try:
                telegram_id_int = int(telegram_id)
                new_balance = add_user_balance(telegram_id_int, amount)
                logger.info(f"💰 Balance actualizado: User {telegram_id_int} = ${new_balance:.2f}")
                
                # 3. Enviar voucher a Telegram
                voucher = (
                    "🎉 <b>PAGO APROBADO</b>\n\n"
                    f"💳 <b>Monto:</b> ${amount:.2f}\n"
                    f"🧾 <b>Transacción:</b> {transaction_id}\n"
                    f"🔐 <b>Autorización:</b> {authorization_code or 'N/A'}\n"
                    f"📅 <b>Fecha:</b> {paid_date or 'N/A'}\n"
                    f"🏷 <b>Referencia:</b> {intent_id_int}\n\n"
                    f"💰 <b>Nuevo saldo:</b> ${new_balance:.2f}\n\n"
                    "Gracias por usar <b>PITIUPI</b> 🚀"
                )
                send_telegram_message(telegram_id_int, voucher)
                
            except ValueError:
                logger.error(f"❌ User ID no válido: {telegram_id}")
            except Exception as e:
                logger.error(f"❌ Error actualizando balance: {e}")

        # 🟡 PAGO CANCELADO (status=2)
        elif status == "2":
            logger.info(f"🟡 Pago CANCELADO → Intent {intent_id_int}")
            update_payment_intent(intent_id_int, status="cancelled")
            
            # Notificar al usuario
            try:
                telegram_id_int = int(telegram_id)
                message = (
                    "❌ <b>PAGO CANCELADO</b>\n\n"
                    f"La transacción {transaction_id} ha sido cancelada.\n"
                    f"Referencia: {intent_id_int}\n\n"
                    "Si crees que es un error, contacta con soporte."
                )
                send_telegram_message(telegram_id_int, message)
            except Exception:
                pass

        # 🔵 OTROS ESTADOS (registramos pero no procesamos)
        else:
            logger.info(f"ℹ️ Estado no procesado: {status}/{status_detail}")
            update_payment_intent(intent_id_int, status=f"webhook_{status}")

        return {"status": "OK"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error inesperado en webhook: {e}", exc_info=True)
        return {"status": "OK"}  # Siempre responder OK para no recibir reintentos


# ============================================================
# ENDPOINT PARA DEBUG (SOLO DESARROLLO)
# ============================================================

@router.get("/debug/stoken")
async def debug_stoken_endpoint(
    transaction_id: str = "TEST-123",
    application_code: str = "TEST-APP-CODE",
    user_id: str = "12345"
):
    """
    Endpoint para verificar cálculo de STOKEN.
    SOLO usar en desarrollo/staging.
    """
    # Validar entorno
    if os.getenv("NUVEI_ENV", "stg") == "prod":
        return {"error": "Endpoint deshabilitado en producción"}
    
    stoken = generate_stoken(transaction_id, application_code, user_id, APP_KEY)
    masked_key = f"...{APP_KEY[-4:]}" if APP_KEY else "N/A"
    
    return {
        "success": True,
        "data": {
            "transaction_id": transaction_id,
            "application_code": application_code,
            "user_id": user_id,
            "app_key_masked": masked_key,
            "raw_string": f"{transaction_id}_{application_code}_{user_id}_{APP_KEY}",
            "stoken": stoken,
            "stoken_first8": stoken[:8]
        },
        "note": "Esta es la fórmula exacta que usa Nuvei para el webhook"
    }


# ============================================================
# ENDPOINT DE SALUD DEL WEBHOOK
# ============================================================

@router.get("/health")
async def webhook_health():
    """Verifica que el webhook esté funcionando correctamente"""
    return {
        "status": "healthy",
        "service": "nuvei_webhook",
        "app_key_configured": bool(APP_KEY),
        "bot_token_configured": bool(BOT_TOKEN),
        "timestamp": datetime.now().isoformat()
    }
