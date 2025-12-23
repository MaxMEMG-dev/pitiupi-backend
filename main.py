# ============================================================
# main.py — PITIUPI Backend Nuvei
# PITIUPI v6.0 — Orchestrator / Adapter (NO DB)
# ============================================================

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
import logging
import os
import sys

from payments_api import router as payments_router
from nuvei_webhook import router as nuvei_router

# ============================================================
# LOGGING CONFIGURATION
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("pitiupi-backend")

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(
    title="PITIUPI Backend Nuvei",
    description="Backend V6 — Nuvei Adapter / Webhook Orchestrator (Stateless)",
    version="6.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================
# CORS MIDDLEWARE (API-to-API + Webhooks)
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción considerar restringir
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("✅ CORS configurado")

# ============================================================
# ROUTERS
# ============================================================
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(nuvei_router, prefix="/nuvei", tags=["Nuvei"])

logger.info("✅ Routers cargados: /payments, /nuvei")

# ============================================================
# BASIC ENDPOINTS
# ============================================================

@app.get("/", tags=["Root"])
def root():
    """
    Endpoint raíz - Información básica del servicio
    """
    return {
        "service": "PITIUPI Backend Nuvei",
        "version": "6.0.0",
        "role": "Adapter / Orchestrator",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """
    Health check completo - Valida configuración de variables de entorno
    """
    return {
        "status": "healthy",
        "version": "6.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "payments_api": True,
            "nuvei_webhook": True,
        },
        "environment": {
            "nuvei_app_code_configured": bool(os.getenv("NUVEI_APP_CODE_SERVER")),
            "nuvei_app_key_configured": bool(os.getenv("NUVEI_APP_KEY_SERVER")),
            "nuvei_env": os.getenv("NUVEI_ENV", "stg"),
            "bot_backend_configured": bool(os.getenv("BOT_BACKEND_URL")),
            "internal_api_key_configured": bool(os.getenv("INTERNAL_API_KEY")),
            "telegram_notifications": bool(os.getenv("BOT_TOKEN")),
        },
    }


@app.get("/info", tags=["Info"])
def info():
    """
    Información arquitectónica del servicio
    """
    return {
        "version": "6.0.0",
        "role": "Nuvei Adapter / Webhook Gateway",
        "architecture": "Stateless Microservice",
        "responsibilities": [
            "Create LinkToPay orders via Nuvei API",
            "Receive and validate Nuvei webhooks (STOKEN validation)",
            "Delegate payment confirmation to Bot Backend",
            "Send Telegram notifications to users",
        ],
        "explicitly_not_responsible_for": [
            "User management",
            "Balance management",
            "Ledger transactions",
            "Database operations",
            "Business rules enforcement",
        ],
        "security": {
            "nuvei_auth": "Auth-Token (SHA256 + Base64)",
            "webhook_validation": "STOKEN (MD5)",
            "internal_calls": "X-Internal-API-Key header",
            "idempotency": "UUID-based (delegated to Bot Backend)",
        },
        "integrations": {
            "nuvei": "LinkToPay API (Ecuador)",
            "bot_backend": "PITIUPI Bot Backend (Internal API)",
            "telegram": "Bot API for notifications",
        },
    }

# ============================================================
# STARTUP EVENT
# ============================================================

@app.on_event("startup")
async def startup_event():
    """
    Evento de inicio - Validación de configuración
    """
    logger.info("=" * 60)
    logger.info("🚀 PITIUPI Backend Nuvei V6 starting")
    logger.info("=" * 60)

    # Variables de entorno requeridas
    required_env_vars = {
        "NUVEI_APP_CODE_SERVER": "Nuvei Application Code",
        "NUVEI_APP_KEY_SERVER": "Nuvei Secret Key",
        "BOT_BACKEND_URL": "Bot Backend URL",
        "INTERNAL_API_KEY": "Internal API Key",
    }

    # Variables opcionales
    optional_env_vars = {
        "BOT_TOKEN": "Telegram Bot Token (for notifications)",
        "NUVEI_ENV": "Nuvei Environment (stg/prod)",
    }

    # Validar variables requeridas
    missing = []
    for var, description in required_env_vars.items():
        value = os.getenv(var)
        if not value:
            missing.append(f"{var} ({description})")
            logger.error(f"❌ Missing: {var}")
        else:
            # Ocultar valores sensibles en logs
            if "KEY" in var or "TOKEN" in var:
                logger.info(f"✅ {var}: ***{value[-4:]}")
            else:
                logger.info(f"✅ {var}: {value}")

    # Validar variables opcionales
    for var, description in optional_env_vars.items():
        value = os.getenv(var)
        if not value:
            logger.warning(f"⚠️ Optional: {var} not configured ({description})")
        else:
            if "TOKEN" in var:
                logger.info(f"✅ {var}: ***{value[-4:]}")
            else:
                logger.info(f"✅ {var}: {value}")

    # Si faltan variables críticas, registrar error pero no detener
    if missing:
        logger.error("=" * 60)
        logger.error("❌ MISSING CRITICAL ENVIRONMENT VARIABLES:")
        for var in missing:
            logger.error(f"   • {var}")
        logger.error("=" * 60)
        logger.error("⚠️ Service may not function correctly!")
    else:
        logger.info("=" * 60)
        logger.info("✅ All required environment variables configured")
        logger.info("=" * 60)

    # Información de seguridad
    logger.info("🔐 Security Configuration:")
    logger.info("   • Nuvei Auth: Auth-Token (SHA256 + Base64)")
    logger.info("   • Webhook: STOKEN validation (MD5)")
    logger.info("   • Internal: X-Internal-API-Key header")

    # Información arquitectónica
    logger.info("🏗️ Architecture:")
    logger.info("   • Role: Stateless Adapter/Orchestrator")
    logger.info("   • Database: None (stateless)")
    logger.info("   • Business Logic: Delegated to Bot Backend")

    # URLs de endpoints
    logger.info("🌐 Available Endpoints:")
    logger.info("   • GET  /              - Root info")
    logger.info("   • GET  /health        - Health check")
    logger.info("   • GET  /info          - Architecture info")
    logger.info("   • GET  /docs          - Swagger UI")
    logger.info("   • GET  /payments/pay  - Payment redirect (from Telegram)")
    logger.info("   • POST /payments/create_payment - Create payment (API)")
    logger.info("   • POST /nuvei/callback - Nuvei webhook")

    logger.info("=" * 60)
    logger.info("✅ Backend ready to receive requests")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Evento de apagado
    """
    logger.info("=" * 60)
    logger.info("🛑 PITIUPI Backend Nuvei shutting down")
    logger.info("=" * 60)

# ============================================================
# GLOBAL EXCEPTION HANDLER
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Manejador global de excepciones no capturadas
    """
    logger.error("=" * 60)
    logger.error("❌ UNHANDLED EXCEPTION")
    logger.error(f"Path: {request.url.path}")
    logger.error(f"Method: {request.method}")
    logger.error(f"Exception: {type(exc).__name__}")
    logger.error(f"Message: {str(exc)}")
    logger.error("=" * 60)
    logger.error("Stack trace:", exc_info=True)

    # En producción, no exponer detalles internos
    if os.getenv("ENV") == "production":
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # En desarrollo, mostrar detalles completos
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.url.path,
            "method": request.method,
        },
    )

# ============================================================
# MIDDLEWARE DE REQUEST LOGGING (OPCIONAL)
# ============================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware para loggear todas las requests
    """
    start_time = datetime.utcnow()
    
    # Loggear request entrante
    logger.info(f"➡️  {request.method} {request.url.path}")
    
    # Procesar request
    response = await call_next(request)
    
    # Calcular tiempo de procesamiento
    process_time = (datetime.utcnow() - start_time).total_seconds()
    
    # Loggear response
    logger.info(
        f"⬅️  {request.method} {request.url.path} "
        f"→ {response.status_code} ({process_time:.3f}s)"
    )
    
    return response

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    logger.info(f"🚀 Starting server on port {port}")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,  # Desactivado en producción
        log_level="info",
    )

# ============================================================
# END OF FILE
# ============================================================
