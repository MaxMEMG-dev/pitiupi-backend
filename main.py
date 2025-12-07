# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

# ----------------------------
# Configuración de logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# ----------------------------
# Importación de routers
# ----------------------------
from nuvei_webhook import router as nuvei_router
from payments_api import router as payments_router

# ----------------------------
# Inicialización de la base de datos
# ----------------------------
from _init_db import run_migrations

# Ejecutar migraciones
logger.info("🔧 Ejecutando inicialización de base de datos...")
run_migrations()


# ----------------------------
# FASTAPI APP
# ----------------------------
app = FastAPI(
    title="Pitiupi Backend",
    description="Backend oficial PITIUPI con integración Nuvei LinkToPay",
    version="1.0.0",
)

# ----------------------------
# CORS CONFIG
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],  # Incluye OPTIONS
    allow_headers=["*"],
)

logger.info("🌍 CORS habilitado correctamente")


# ----------------------------
# Registrar Routers
# ----------------------------
app.include_router(nuvei_router, prefix="/nuvei", tags=["Nuvei"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])

logger.info("📦 Routers registrados exitosamente")


# ----------------------------
# Endpoint raíz
# ----------------------------
@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Pitiupi Backend listo 🚀"
    }


# ----------------------------
# Debug credenciales Nuvei
# ----------------------------
@app.get("/debug/nuvei")
def debug_nuvei():
    return {
        "NUVEI_APP_CODE_SERVER": os.getenv("NUVEI_APP_CODE_SERVER"),
        "NUVEI_APP_KEY_SERVER": os.getenv("NUVEI_APP_KEY_SERVER"),
        "NUVEI_ENV": os.getenv("NUVEI_ENV"),
    }


# ----------------------------
# Stats – para monitoreo
# ----------------------------
@app.get("/stats")
def stats():
    """Devuelve estadísticas generales del sistema PITIUPI."""
    return {
        "status": "ok",
        "database": "connected",
        "payments_module": "ready",
        "nuvei_module": "ready",
        "version": "1.0.0"
    }

