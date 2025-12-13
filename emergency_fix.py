# emergency_fix.py
from fastapi import APIRouter, HTTPException
import os
import logging
from database import get_connection

router = APIRouter(tags=["Emergency"])
logger = logging.getLogger(__name__)

@router.post("/fix-payments-now")
async def fix_payments_now():
    """
    Endpoint de emergencia para arreglar payment_intents y balance.
    Solo ejecutar UNA VEZ.
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. PRIMERO: Asegurar que el usuario existe
        cursor.execute("""
            INSERT INTO users (
                telegram_id, 
                telegram_first_name, 
                email, 
                balance, 
                created_at
            )
            VALUES (
                1503360966, 
                'Usuario Test', 
                'test@example.com', 
                0.00, 
                NOW()
            )
            ON CONFLICT (telegram_id) DO NOTHING
            RETURNING id;
        """)
        
        user_result = cursor.fetchone()
        user_id = user_result["id"] if user_result else None
        
        if not user_id:
            # Si ya existe, obtener su ID
            cursor.execute("SELECT id FROM users WHERE telegram_id = 1503360966")
            existing_user = cursor.fetchone()
            user_id = existing_user["id"] if existing_user else None
        
        logger.info(f"✅ Usuario: ID={user_id}, TelegramID=1503360966")
        
        # 2. SEGUNDO: Actualizar todos los payment_intents con:
        #    - user_id correcto
        #    - application_code correcto
        #    - telegram_id (si falta)
        
        app_code = os.getenv("NUVEI_APP_CODE_SERVER", "LINKTOPAY01-EC-SERVER")
        
        cursor.execute("""
            UPDATE payment_intents 
            SET 
                user_id = %s,
                telegram_id = 1503360966,
                application_code = %s
            WHERE telegram_id = 1503360966 OR user_id = 1503360966;
        """, (user_id, app_code))
        
        updated_count = cursor.rowcount
        logger.info(f"✅ {updated_count} payment_intents actualizados")
        
        # 3. TERCERO: Marcar el intent 56 como pagado MANUALMENTE
        # (para pruebas, simular que el webhook funcionó)
        
        cursor.execute("""
            UPDATE payment_intents 
            SET 
                status = 'paid',
                transaction_id = 'MANUAL-FIX-TX-001',
                authorization_code = 'MANUAL-AUTH-001',
                status_detail = 3,
                paid_at = NOW(),
                message = 'Corregido manualmente por emergency_fix'
            WHERE id = 56 AND status = 'pending';
        """)
        
        if cursor.rowcount > 0:
            logger.info("✅ Intent 56 marcado como PAID manualmente")
        
        # 4. CUARTO: Sumar balance manualmente
        cursor.execute("""
            UPDATE users 
            SET balance = COALESCE(balance, 0) + 10.00
            WHERE telegram_id = 1503360966
            RETURNING balance;
        """)
        
        balance_result = cursor.fetchone()
        new_balance = balance_result["balance"] if balance_result else 0
        
        conn.commit()
        
        # 5. QUINTO: Verificar resultado
        cursor.execute("""
            SELECT 
                pi.id as intent_id,
                pi.status,
                pi.amount,
                pi.transaction_id,
                pi.paid_at,
                u.telegram_id,
                u.balance
            FROM payment_intents pi
            LEFT JOIN users u ON u.id = pi.user_id
            WHERE pi.id = 56;
        """)
        
        final_check = cursor.fetchone()
        
        return {
            "success": True,
            "message": "✅ Sistema corregido manualmente",
            "data": {
                "user_id": user_id,
                "payment_intents_updated": updated_count,
                "intent_56_status": final_check["status"] if final_check else "not_found",
                "intent_56_paid_at": final_check["paid_at"] if final_check else None,
                "user_balance": float(new_balance)
            }
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error en fix: {e}", exc_info=True)
        raise HTTPException(500, f"Error: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.get("/check-status")
async def check_status():
    """Verificar estado actual del sistema"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Verificar usuario
        cursor.execute("""
            SELECT id, telegram_id, balance 
            FROM users 
            WHERE telegram_id = 1503360966;
        """)
        user = cursor.fetchone()
        
        # 2. Verificar payment_intents
        cursor.execute("""
            SELECT 
                id, user_id, telegram_id, amount, status,
                transaction_id, paid_at, application_code
            FROM payment_intents 
            WHERE telegram_id = 1503360966 
            ORDER BY id DESC 
            LIMIT 5;
        """)
        payments = cursor.fetchall()
        
        # 3. Verificar estructura de tablas
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'payment_intents' 
            AND column_name IN ('user_id', 'telegram_id', 'application_code');
        """)
        columns = cursor.fetchall()
        
        return {
            "success": True,
            "user": user,
            "payments": payments,
            "table_columns": columns,
            "diagnosis": {
                "user_exists": user is not None,
                "user_has_balance": user and user["balance"] is not None,
                "has_telegram_id_column": any(c["column_name"] == "telegram_id" for c in columns),
                "has_app_code_column": any(c["column_name"] == "application_code" for c in columns)
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error check: {e}")
        raise HTTPException(500, str(e))
    finally:
        if conn:
            conn.close()
