# ============================================================
# nuvei_webhook.py — Callback oficial Nuvei
# PITIUPI v5.1 — STOKEN CORREGIDO (SIMPLIFICADO)
# ============================================================

from fastapi import APIRouter, Request, HTTPException
import hashlib
import logging
import os
import requests
from datetime import datetime

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

if not APP_KEY:
    logger.critical("❌ NUVEI_APP_KEY_SERVER no configurado")
    APP_KEY = "G8vwvaASAZHQgoVuF2eKZyZF5hJmvx"  # Fallback para pruebas

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN no configurado - Notificaciones desactivadas")


# ============================================================
# STOKEN — FÓRMULA OFICIAL
# ============================================================
def generate_stoken(
    transaction_id: str,
    application_code: str,
    user_id: str,
    app_key: str
) -> str:
    """Genera stoken según documentación Nuvei."""
    raw = f"{transaction_id}_{application_code}_{user_id}_{app_key}"
    stoken = hashlib.md5(raw.encode()).hexdigest()
    
    logger.debug(f"🔑 STOKEN: {raw[:50]}... → {stoken[:8]}...")
    return stoken


# ============================================================
# ENVÍO A TELEGRAM
# ============================================================
def send_telegram_message(chat_id: int, text: str):
    if not BOT_TOKEN:
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
        
        if response.status_code == 200:
            logger.info(f"📱 Mensaje enviado a Telegram ID: {chat_id}")
        else:
            logger.error(f"❌ Telegram error {response.status_code}: {response.text[:100]}")
            
    except Exception as e:
        logger.error(f"❌ Error enviando a Telegram: {e}")


# ============================================================
# WEBHOOK NUVEI (SIMPLIFICADO Y ROBUSTO)
# ============================================================
@router.post("/callback")
async def nuvei_callback(request: Request):
    try:
        # 1️⃣ Obtener payload
        payload = await request.json()
        logger.info("📥 Webhook Nuvei recibido")
        
        tx = payload.get("transaction")
        user = payload.get("user", {})
        
        if not tx:
            logger.warning("⚠️ Sin transaction en webhook")
            return {"status": "OK"}
        
        # 2️⃣ Extraer datos básicos
        transaction_id = tx.get("id")
        status = str(tx.get("status", ""))
        status_detail = str(tx.get("status_detail", ""))
        intent_id = tx.get("dev_reference")
        application_code = tx.get("application_code")
        amount = float(tx.get("amount", 0))
        telegram_id = user.get("id")  # ¡String!
        
        # 3️⃣ Validar campos obligatorios
        if not all([transaction_id, intent_id, telegram_id, application_code]):
            logger.warning("⚠️ Webhook incompleto")
            return {"status": "OK"}
        
        # 4️⃣ Validar STOKEN
        sent_stoken = tx.get("stoken")
        expected_stoken = generate_stoken(
            transaction_id=transaction_id,
            application_code=application_code,
            user_id=str(telegram_id),
            app_key=APP_KEY
        )
        
        logger.info(f"🔍 STOKEN comparación:")
        logger.info(f"   Recibido: {sent_stoken}")
        logger.info(f"   Esperado: {expected_stoken}")
        
        if sent_stoken != expected_stoken:
            logger.error("❌ STOKEN inválido")
            raise HTTPException(status_code=203, detail="Token error")
        
        logger.info("✅ STOKEN válido")
        
        # 5️⃣ Convertir intent_id a int
        try:
            intent_id_int = int(intent_id)
        except ValueError:
            logger.error(f"❌ intent_id no es numérico: {intent_id}")
            return {"status": "OK"}
        
        # 6️⃣ Obtener intent
        intent = get_payment_intent(intent_id_int)
        if not intent:
            logger.error(f"❌ Intent {intent_id_int} no existe")
            return {"status": "OK"}
        
        # 7️⃣ Idempotencia
        if intent.get("status") == "paid":
            logger.info(f"🔁 Intent {intent_id_int} ya pagado")
            return {"status": "OK"}
        
        # 8️⃣ Validar monto
        intent_amount = float(intent.get("amount", 0))
        if abs(intent_amount - amount) > 0.01:
            logger.error(f"❌ Monto no coincide: BD=${intent_amount:.2f} vs Webhook=${amount:.2f}")
            update_payment_intent(intent_id_int, status="error", message="Monto no coincide")
            return {"status": "OK"}
        
        # 9️⃣ Procesar según estado
        if status == "1" and status_detail == "3":  # APROBADO
            logger.info(f"🟢 PAGO APROBADO | Intent {intent_id_int} | ${amount:.2f}")
            
            # Marcar como pagado
            mark_intent_paid(
                intent_id=intent_id_int,
                provider_tx_id=transaction_id,
                status_detail=int(status_detail),
                authorization_code=tx.get("authorization_code", ""),
                message="Pago aprobado por Nuvei"
            )
            
            # Sumar balance
            try:
                telegram_id_int = int(telegram_id)
                new_balance = add_user_balance(telegram_id_int, amount)
                
                # Enviar notificación
                voucher = (
                    "🎉 <b>PAGO APROBADO</b>\n\n"
                    f"💳 <b>Monto:</b> ${amount:.2f}\n"
                    f"🧾 <b>Transacción:</b> {transaction_id}\n"
                    f"🔐 <b>Autorización:</b> {tx.get('authorization_code', 'N/A')}\n"
                    f"🏷 <b>Referencia:</b> {intent_id_int}\n\n"
                    f"💰 <b>Nuevo saldo:</b> ${new_balance:.2f}\n\n"
                    "Gracias por usar <b>PITIUPI</b> 🚀"
                )
                send_telegram_message(telegram_id_int, voucher)
                
            except Exception as e:
                logger.error(f"❌ Error actualizando balance: {e}")
                
        elif status == "2":  # CANCELADO
            logger.info(f"🟡 PAGO CANCELADO | Intent {intent_id_int}")
            update_payment_intent(intent_id_int, status="cancelled")
            
        else:
            logger.info(f"ℹ️ Estado no procesado: {status}/{status_detail}")
        
        return {"status": "OK"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en webhook: {e}", exc_info=True)
        return {"status": "OK"}


# ============================================================
# ENDPOINT DE SALUD
# ============================================================
@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "nuvei_webhook",
        "app_key_configured": bool(APP_KEY),
        "timestamp": datetime.now().isoformat()
    }
