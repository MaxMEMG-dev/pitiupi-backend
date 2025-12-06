# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# Routers (ajustados a tu estructura real)
from nuvei_webhook import router as nuvei_router
from payments_api import router as payments_router

# Inicialización de la base de datos
from database import init_db


app = FastAPI(
    title="Pitiupi Backend",
    description="Backend con integración Nuvei LinkToPay",
    version="1.0.0",
)

# ----------------------------
# CORS – PERMITE OPTIONS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],   # Permite OPTIONS
    allow_headers=["*"],
)

# ----------------------------
# Inicializar base de datos
# ----------------------------
init_db()

# ----------------------------
# Registrar los routers
# ----------------------------
app.include_router(nuvei_router, prefix="/nuvei", tags=["Nuvei"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])

# ----------------------------
# Endpoint raíz
# ----------------------------
@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Pitiupi Backend listo"
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
# Stats – simple placeholder
# ----------------------------
@app.get("/stats")
def stats():
    """Devuelve estadísticas generales del sistema PITIUPI."""
    return {
        "status": "ok",
        "db": "connected",
        "payments": "ready",
        "nuvei": "ready",
    }
