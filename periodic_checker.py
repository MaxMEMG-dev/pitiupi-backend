# periodic_checker.py
import logging
import asyncio
from datetime import datetime
import os
from database import get_connection

logger = logging.getLogger(__name__)

async def check_and_process_payments():
    """Revisa pagos pendientes y los procesa automáticamente"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Buscar TODOS los payment_intents pendientes
        cursor.execute("""
            SELECT 
                id, telegram_id, amount, created_at,
                order_id, application_code
            FROM payment_intents 
            WHERE status = 'pending'
            ORDER BY created_at;
        """)
        
        pending_intents = cursor.fetchall()
        
        if not pending_intents:
            logger.info("🔍 No hay pagos pendientes")
            return
        
        logger.info(f"🔍 Encontrados {len(pending_intents)} pagos pendientes")
        
        # 2. Para CADA intent pendiente, simular que fue pagado
        for intent in pending_intents:
            intent_id = intent["id"]
            telegram_id = intent["telegram_id"]
            amount = float(intent["amount"])
            order_id = intent["order_id"]
            
            # 3. Verificar si el pago tiene más de 2 minutos (para dar tiempo al usuario)
            created_at = intent["created_at"]
            time_diff = datetime.now() - created_at
            minutes_diff = time_diff.total_seconds() / 60
            
            if minutes_diff < 2:
                logger.info(f"⏳ Intent {intent_id} muy reciente ({minutes_diff:.1f} min), esperando...")
                continue
            
            # 4. Simular datos de transacción Nuvei
            transaction_id = f"AUTO-{order_id}"
            authorization_code = f"AUTH-{intent_id}"
            
            # 5. Marcar como pagado en la base de datos
            cursor.execute("""
                UPDATE payment_intents 
                SET 
                    status = 'paid',
                    transaction_id = %s,
                    authorization_code = %s,
                    status_detail = 3,
                    paid_at = NOW(),
                    application_code = COALESCE(application_code, %s),
                    message = 'Procesado automáticamente - Esperando webhook Nuvei'
                WHERE id = %s AND status = 'pending';
            """, (
                transaction_id,
                authorization_code,
                os.getenv("NUVEI_APP_CODE_SERVER", "LINKTOPAY01-EC-SERVER"),
                intent_id
            ))
            
            if cursor.rowcount > 0:
                # 6. Sumar el monto al balance del usuario
                cursor.execute("""
                    UPDATE users 
                    SET balance = COALESCE(balance, 0) + %s
                    WHERE telegram_id = %s
                    RETURNING balance;
                """, (amount, telegram_id))
                
                balance_result = cursor.fetchone()
                new_balance = float(balance_result["balance"]) if balance_result else 0
                
                logger.info(f"✅ Intent {intent_id} procesado: +${amount:.2f} para usuario {telegram_id}")
                logger.info(f"💰 Nuevo balance: ${new_balance:.2f}")
                
                # 7. Opcional: Enviar notificación a Telegram
                try:
                    await send_telegram_notification(telegram_id, intent_id, amount, new_balance)
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo enviar notificación a Telegram: {e}")
        
        conn.commit()
        logger.info(f"✅ Proceso completado: {len(pending_intents)} intents revisados")
        
    except Exception as e:
        logger.error(f"❌ Error en check_and_process_payments: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

async def send_telegram_notification(telegram_id: int, intent_id: int, amount: float, new_balance: float):
    """Envía notificación a Telegram"""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        return
    
    import requests
    
    message = (
        f"🎉 <b>PAGO PROCESADO (Modo Manual)</b>\n\n"
        f"💳 <b>Monto:</b> ${amount:.2f}\n"
        f"🏷 <b>Referencia:</b> {intent_id}\n"
        f"💰 <b>Nuevo saldo:</b> ${new_balance:.2f}\n\n"
        f"<i>Nota: Esto se procesó automáticamente mientras configuramos Nuvei.</i>\n"
        f"<i>El lunes se activará el sistema oficial.</i>"
    )
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if response.status_code == 200:
            logger.info(f"📱 Notificación enviada a Telegram ID: {telegram_id}")
    except Exception as e:
        logger.error(f"❌ Error enviando a Telegram: {e}")
