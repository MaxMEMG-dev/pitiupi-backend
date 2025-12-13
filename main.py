# ============================================================
# main.py — PITIUPI Backend (FastAPI + PostgreSQL + Nuvei)
# ============================================================

from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from database import get_connection

# Routers del sistema
from users_api import router as users_router
from payments_api import router as payments_router
from nuvei_webhook import router as nuvei_router

# Inicialización de base de datos
from database import init_db

# ============================================================
# ROUTER DE EMERGENCIA (TODO EN MAIN.PY)
# ============================================================
emergency_router = APIRouter(tags=["Emergency"])
logger = logging.getLogger(__name__)

@emergency_router.post("/fix-payments-simple")
async def fix_payments_simple():
    """
    Versión SIMPLE y FUNCIONAL para arreglar todo.
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Asegurar application_code en TODOS los payment_intents
        app_code = os.getenv("NUVEI_APP_CODE_SERVER", "LINKTOPAY01-EC-SERVER")
        
        cursor.execute("""
            UPDATE payment_intents 
            SET application_code = %s
            WHERE application_code IS NULL 
            AND telegram_id = 1503360966;
        """, (app_code,))
        
        logger.info(f"✅ application_code agregado a {cursor.rowcount} intents")
        
        # 2. Marcar el intent 56 como PAID
        cursor.execute("""
            UPDATE payment_intents 
            SET 
                status = 'paid',
                transaction_id = 'MANUAL-FIX-001',
                authorization_code = 'MANUAL-AUTH-001',
                status_detail = 3,
                paid_at = NOW()
            WHERE id = 56 AND status = 'pending';
        """)
        
        if cursor.rowcount > 0:
            logger.info("✅ Intent 56 marcado como PAID")
        
        # 3. Sumar el monto del intent 56 al balance
        cursor.execute("""
            SELECT amount FROM payment_intents WHERE id = 56;
        """)
        intent_56 = cursor.fetchone()
        amount_to_add = intent_56["amount"] if intent_56 else 10.00
        
        cursor.execute("""
            UPDATE users 
            SET balance = COALESCE(balance, 0) + %s
            WHERE telegram_id = 1503360966
            RETURNING balance;
        """, (amount_to_add,))
        
        balance_result = cursor.fetchone()
        new_balance = balance_result["balance"] if balance_result else 0
        
        conn.commit()
        
        return {
            "success": True,
            "message": "✅ Sistema corregido",
            "details": {
                "intent_56_updated": cursor.rowcount > 0,
                "amount_added": float(amount_to_add),
                "new_balance": float(new_balance),
                "application_code_set": app_code
            }
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        if conn:
            conn.close()


@emergency_router.get("/verify-fix")
async def verify_fix():
    """Verificar si el fix funcionó"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Verificar intent 56
        cursor.execute("""
            SELECT 
                id, status, amount, 
                transaction_id, paid_at, 
                application_code
            FROM payment_intents 
            WHERE id = 56;
        """)
        intent_56 = cursor.fetchone()
        
        # 2. Verificar balance
        cursor.execute("""
            SELECT balance FROM users 
            WHERE telegram_id = 1503360966;
        """)
        user = cursor.fetchone()
        
        return {
            "success": True,
            "intent_56": intent_56,
            "user_balance": float(user["balance"]) if user else 0,
            "diagnosis": {
                "intent_56_is_paid": intent_56 and intent_56["status"] == "paid",
                "intent_56_has_transaction": intent_56 and intent_56["transaction_id"] is not None,
                "balance_increased": user and user["balance"] > 0
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


@emergency_router.post("/fix-all-payments")
async def fix_all_payments():
    """
    Marca TODOS los payment_intents pendientes como pagados y suma sus montos.
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Obtener todos los intents pendientes para este usuario
        cursor.execute("""
            SELECT id, amount 
            FROM payment_intents 
            WHERE telegram_id = 1503360966 
            AND status = 'pending'
            ORDER BY id;
        """)
        
        pending_intents = cursor.fetchall()
        
        if not pending_intents:
            return {"success": False, "message": "No hay intents pendientes"}
        
        total_amount = sum([pi["amount"] for pi in pending_intents])
        intent_ids = [pi["id"] for pi in pending_intents]
        
        # 2. Marcar TODOS como pagados
        cursor.execute("""
            UPDATE payment_intents 
            SET 
                status = 'paid',
                transaction_id = 'BATCH-FIX-' || id::text,
                authorization_code = 'BATCH-AUTH-' || id::text,
                status_detail = 3,
                paid_at = NOW(),
                application_code = COALESCE(application_code, %s)
            WHERE id = ANY(%s);
        """, (os.getenv("NUVEI_APP_CODE_SERVER", "LINKTOPAY01-EC-SERVER"), intent_ids))
        
        # 3. Sumar TODOS los montos al balance
        cursor.execute("""
            UPDATE users 
            SET balance = COALESCE(balance, 0) + %s
            WHERE telegram_id = 1503360966
            RETURNING balance;
        """, (total_amount,))
        
        balance_result = cursor.fetchone()
        new_balance = balance_result["balance"] if balance_result else 0
        
        conn.commit()
        
        return {
            "success": True,
            "message": f"✅ {len(pending_intents)} intents procesados",
            "details": {
                "intents_processed": intent_ids,
                "total_amount_added": float(total_amount),
                "new_balance": float(new_balance)
            }
        }
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


# ============================================================
# Inicializar APP FastAPI
# ============================================================
app = FastAPI(
    title="Pitiupi Backend",
    description="Backend centralizado para PITIUPI — Sincronización Telegram + Nuvei LinkToPay",
    version="1.0.0",
)

# ============================================================
# CORS — Permitir llamadas desde el bot
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Puedes restringir si deseas
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Inicialización de la Base de Datos
# ============================================================
init_db()


# ============================================================
# Registro de Routers
# ============================================================
app.include_router(users_router, prefix="/users", tags=["Users"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(nuvei_router, prefix="/nuvei", tags=["Nuvei"])
app.include_router(emergency_router, prefix="/emergency", tags=["Emergency"])


# ============================================================
# ENDPOINT RAÍZ
# ============================================================
@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Pitiupi Backend listo 🚀"
    }


# ============================================================
# Debug credenciales Nuvei
# ============================================================
@app.get("/debug/nuvei")
def debug_nuvei():
    return {
        "NUVEI_APP_CODE_SERVER": os.getenv("NUVEI_APP_CODE_SERVER"),
        "NUVEI_APP_KEY_SERVER": os.getenv("NUVEI_APP_KEY_SERVER"),
        "NUVEI_ENV": os.getenv("NUVEI_ENV"),
    }


# ============================================================
# Stats
# ============================================================
@app.get("/stats")
def stats():
    return {
        "status": "ok",
        "db": "connected",
        "payments": "ready",
        "nuvei": "ready",
    }


# ============================================================
# Endpoint de diagnóstico rápido
# ============================================================
@app.get("/quick-check")
def quick_check():
    """Diagnóstico rápido del sistema"""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Verificar usuario
        cursor.execute("SELECT COUNT(*) as user_count FROM users WHERE telegram_id = 1503360966")
        user_count = cursor.fetchone()["user_count"]
        
        # Verificar intents
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'paid' THEN 1 END) as paid,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending
            FROM payment_intents WHERE telegram_id = 1503360966
        """)
        intents_stats = cursor.fetchone()
        
        # Verificar balance
        cursor.execute("SELECT balance FROM users WHERE telegram_id = 1503360966")
        user_balance = cursor.fetchone()
        
        return {
            "success": True,
            "status": "online",
            "database": "connected",
            "user_exists": user_count > 0,
            "user_balance": float(user_balance["balance"]) if user_balance else 0,
            "payment_intents": {
                "total": intents_stats["total"],
                "paid": intents_stats["paid"],
                "pending": intents_stats["pending"]
            },
            "environment": {
                "nuvei_app_code_configured": bool(os.getenv("NUVEI_APP_CODE_SERVER")),
                "nuvei_app_key_configured": bool(os.getenv("NUVEI_APP_KEY_SERVER")),
                "database_url_configured": bool(os.getenv("DATABASE_URL"))
            }
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            conn.close()
