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

from payments_api import router as payments_router
from nuvei_webhook import router as nuvei_router

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pitiupi-backend")

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(
    title="PITIUPI Backend Nuvei",
    description="Backend V6 — Nuvei Adapter / Webhook Orchestrator",
    version="6.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================
# CORS (API-to-API + Webhooks)
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return {
        "service": "PITIUPI Backend Nuvei",
        "version": "6.0.0",
        "role": "Adapter / Orchestrator",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "version": "6.0.0",
        "services": {
            "payments_api": True,
            "nuvei_webhook": True,
        },
        "environment": {
            "nuvei_configured": bool(os.getenv("NUVEI_APP_CODE_SERVER")),
            "bot_backend_configured": bool(os.getenv("BOT_BACKEND_URL")),
            "internal_api_key_configured": bool(os.getenv("INTERNAL_API_KEY")),
            "telegram_notifications": bool(os.getenv("BOT_TOKEN")),
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/info", tags=["Info"])
def info():
    """
    Información arquitectónica REAL de este servicio
    """
    return {
        "version": "6.0.0",
        "role": "Nuvei Adapter / Webhook Gateway",
        "responsibilities": [
            "Create LinkToPay orders via Nuvei",
            "Receive and validate Nuvei webhooks (STOKEN)",
            "Delegate payment confirmation to BOT backend",
        ],
        "explicitly_not_responsible_for": [
            "Users",
            "Balances",
            "Ledger",
            "Database access",
            "Business rules",
        ],
        "security": {
            "webhook": "STOKEN (MD5)",
            "internal_calls": "X-Internal-API-Key",
            "idempotency": "UUID-based (delegated to bot)",
        },
    }

# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("🚀 PITIUPI Backend Nuvei V6 starting")
    logger.info("=" * 60)

    required_env_vars = [
        "NUVEI_APP_CODE_SERVER",
        "NUVEI_APP_KEY_SERVER",
        "BOT_BACKEND_URL",
        "INTERNAL_API_KEY",
    ]

    missing = [v for v in required_env_vars if not os.getenv(v)]
    if missing:
        logger.warning(f"⚠️ Missing env vars: {', '.join(missing)}")
    else:
        logger.info("✅ All required env vars configured")

    logger.info("🔐 Security: STOKEN + Internal API Key")
    logger.info("💡 No database, no ledger, no business logic here")
    logger.info("=" * 60)
    logger.info("✅ Backend ready")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 PITIUPI Backend Nuvei shutting down")

# ============================================================
# GLOBAL EXCEPTION HANDLER
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("❌ Unhandled exception", exc_info=True)

    if os.getenv("ENV") == "production":
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

# ============================================================
# END OF FILE
# ============================================================
