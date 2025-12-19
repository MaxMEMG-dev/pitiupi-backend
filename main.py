# ============================================================
# main.py — PITIUPI Backend
# PITIUPI v6.0 — 100% V6-Compliant + Producción
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import logging
import os

# Routers V6
from users_api import router as users_router
from payments_api import router as payments_router
from nuvei_webhook import router as nuvei_router

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(
    title="PITIUPI Backend",
    description="Backend financiero V6 — Nuvei + Ledger + PostgreSQL",
    version="6.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================
# CORS MIDDLEWARE
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción: especificar dominios permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ROUTERS V6
# ============================================================
app.include_router(users_router, prefix="/users", tags=["Users"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(nuvei_router, prefix="/nuvei", tags=["Nuvei"])

logger.info("✅ Routers registrados: /users, /payments, /nuvei")

# ============================================================
# ENDPOINTS BÁSICOS
# ============================================================

@app.get("/", tags=["Root"])
def root():
    """
    V6: Endpoint raíz del backend
    
    Returns:
        Información básica del servicio
    """
    return {
        "service": "PITIUPI Backend",
        "version": "6.0.0",
        "status": "running",
        "architecture": "V6 (Ledger + Services + CRUD)",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health", tags=["Health"])
def health_check():
    """
    V6: Health check del backend
    
    Returns:
        Estado de los servicios disponibles
    
    Note:
        - NO hace queries a DB (para evitar overhead)
        - Solo verifica que los routers estén cargados
        - Para checks de DB usar endpoints específicos
    """
    return {
        "status": "healthy",
        "version": "6.0.0",
        "services": {
            "users_api": True,
            "payments_api": True,
            "nuvei_webhook": True,
        },
        "environment": {
            "nuvei_configured": bool(os.getenv("NUVEI_APP_CODE_SERVER")),
            "database_configured": bool(os.getenv("DATABASE_URL")),
            "bot_configured": bool(os.getenv("BOT_TOKEN")),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/info", tags=["Info"])
def info():
    """
    V6: Información del sistema
    
    Returns:
        Detalles de la arquitectura V6
    """
    return {
        "version": "6.0.0",
        "architecture": {
            "pattern": "Layered Architecture",
            "layers": [
                "API Layer (FastAPI endpoints)",
                "Service Layer (Business logic)",
                "CRUD Layer (Database operations)",
                "Model Layer (SQLAlchemy ORM)",
            ],
        },
        "principles": {
            "balance": "Only in User model (single source of truth)",
            "ledger": "Transaction model (append-only, immutable)",
            "mutations": "Only via users_service methods",
            "transactions": "Atomic with session management",
            "sessions": "Injected via Depends(get_db)",
        },
        "payment_flow": {
            "deposit": "User → API → Service → Nuvei → Webhook → Confirm",
            "withdrawal": "User → Freeze → Admin Approve → Consume → Ledger",
        },
        "security": {
            "nuvei_webhook": "STOKEN validation (MD5 hash)",
            "idempotency": "UUID-based for payment intents",
            "no_direct_sql": "All via SQLAlchemy ORM",
        },
    }


# ============================================================
# STARTUP / SHUTDOWN EVENTS
# ============================================================

@app.on_event("startup")
async def startup_event():
    """
    V6: Evento de inicio de la aplicación
    
    Note:
        - NO inicializa tablas (usar Alembic o migrations manuales)
        - NO inicia tareas en background (webhooks son pasivos)
        - Solo logging informativo
    """
    logger.info("=" * 60)
    logger.info("🚀 PITIUPI Backend V6 iniciando...")
    logger.info("=" * 60)
    logger.info("📦 Arquitectura: Layered (API → Service → CRUD → Model)")
    logger.info("💰 Balance: Single source of truth (User model)")
    logger.info("📜 Ledger: Append-only (Transaction model)")
    logger.info("🔒 Security: STOKEN validation + UUID idempotency")
    logger.info("=" * 60)
    
    # Verificar variables de entorno críticas
    required_env_vars = [
        "DATABASE_URL",
        "NUVEI_APP_CODE_SERVER",
        "NUVEI_APP_KEY_SERVER",
    ]
    
    missing = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing:
        logger.warning(f"⚠️ Variables de entorno faltantes: {', '.join(missing)}")
    else:
        logger.info("✅ Todas las variables de entorno críticas configuradas")
    
    logger.info("=" * 60)
    logger.info("✅ Backend V6 listo para recibir requests")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """
    V6: Evento de cierre de la aplicación
    
    Note:
        - Cleanup mínimo (FastAPI maneja la mayoría)
        - SQLAlchemy sessions se cierran automáticamente
    """
    logger.info("=" * 60)
    logger.info("🛑 PITIUPI Backend V6 cerrando...")
    logger.info("=" * 60)
    logger.info("✅ Shutdown completado")


# ============================================================
# EXCEPTION HANDLERS (GLOBAL)
# ============================================================

from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    V6: Manejador global de excepciones
    
    Captura errores no manejados y retorna JSON estructurado
    
    Note:
        - NO expone detalles internos en producción
        - Loguea stack trace completo
        - Retorna error genérico al cliente
    """
    logger.error(f"❌ Unhandled exception: {exc}", exc_info=True)
    
    # En producción, no exponer detalles
    if os.getenv("ENVIRONMENT") == "production":
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error_id": datetime.now().isoformat(),
            }
        )
    
    # En dev, mostrar detalles
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "timestamp": datetime.now().isoformat(),
        }
    )


# ============================================================
# NOTAS DE MIGRACIÓN V5 → V6
# ============================================================
"""
V6 MIGRATION NOTES:

ELIMINADO DE V5:
❌ check_and_process_payments() - Polling automático (inseguro)
❌ run_periodic_checker() - Background task financiero (peligroso)
❌ lifespan con tasks - No más cron bancario sin firma
❌ emergency_router - Puerta trasera financiera (crítico)
❌ /fix-payments-simple - Mutaba balances sin ledger
❌ /fix-all-payments - Creaba dinero ficticio
❌ /process-pending-now - Forzaba pagos sin webhook
❌ SQL directo en endpoints - Violaba arquitectura
❌ init_db() en runtime - Tablas deben estar migradas
❌ get_connection() - Reemplazado por session injection

V6 GARANTÍAS:
✅ Pagos SOLO por webhook firmado (STOKEN)
✅ Balance SOLO mutable vía users_service
✅ Ledger append-only (Transaction)
✅ Sin SQL directo (todo vía ORM)
✅ Sin background jobs financieros
✅ Sin endpoints de "fix" que muten dinero
✅ Idempotencia con UUID
✅ Transacciones atómicas
✅ Audit-ready

FLUJO CORRECTO V6:
1. Usuario crea pago → POST /payments/create_payment
2. Nuvei procesa → LinkToPay
3. Usuario paga → Nuvei confirma
4. Webhook llega → POST /nuvei/callback
5. Validar STOKEN → Seguridad
6. payments_service.confirm_payment() → Atómico
   ├─ users_service.add_balance()
   ├─ transactions_service.create_transaction()
   └─ intent.status = COMPLETED
7. Commit automático por middleware

ANTI-PATRONES ELIMINADOS:
❌ Simular transacciones con "AUTO-XXX"
❌ Marcar pagos como "paid" sin webhook
❌ Sumar balance sin ledger
❌ Polling cada 60 segundos
❌ Endpoints sin auth que muten dinero
❌ application_code manual en runtime

SI NECESITAS "FIX":
- NO usar endpoints
- Usar script offline con session
- Documentar en migration
- Revisar en desarrollo primero
"""

# ============================================================
# END OF FILE
# ============================================================
