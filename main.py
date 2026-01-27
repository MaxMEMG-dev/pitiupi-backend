# ============================================================
# main.py — PITIUPI Backend Stripe
# PITIUPI v6.5.1 — Migración a Stripe + Users Sync API
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import sys
import os

# Configuración de logs mejorada
logging.basicConfig(
    level=logging.INFO, 
    stream=sys.stdout,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pitiupi-backend")

app = FastAPI(title="PITIUPI Backend Stripe", version="6.5.1")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# IMPORTAR ROUTERS
try:
    from payments_api import router as payments_router
    logger.info("✅ payments_api importado correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando payments_api: {e}")
    payments_router = None

try:
    from stripe_webhook import router as stripe_router
    logger.info("✅ stripe_webhook importado correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando stripe_webhook: {e}")
    stripe_router = None

try:
    from users_api import router as users_router
    logger.info("✅ users_api importado correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando users_api: {e}")
    users_router = None

# MONTAR ROUTERS
if payments_router:
    app.include_router(payments_router, prefix="/payments", tags=["Payments"])
    logger.info("✅ Ruta /payments registrada")

if stripe_router:
    app.include_router(stripe_router, prefix="/webhooks/stripe", tags=["Stripe Webhook"])
    logger.info("✅ Ruta /webhooks/stripe registrada")

if users_router:
    app.include_router(users_router, prefix="/users", tags=["Users"])
    logger.info("✅ Ruta /users registrada")

# Root endpoint - Acepta GET y HEAD
@app.get("/")
@app.head("/")
def root():
    return {
        "service": "PITIUPI Backend Stripe", 
        "version": "6.5.1",
        "status": "running"
    }

@app.get("/health")
@app.head("/health")
def health():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.get("/debug-routes")
def debug_routes():
    """Muestra todas las rutas registradas"""
    routes = []
    for route in app.routes:
        if hasattr(route, 'methods'):
            routes.append({
                "path": route.path,
                "methods": list(route.methods),
                "name": route.name
            })
    return {"routes": routes}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port)
