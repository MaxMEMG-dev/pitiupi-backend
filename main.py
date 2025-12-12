# ============================================================
# main.py — PITIUPI Backend (FastAPI + PostgreSQL + Nuvei)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# Routers del sistema
from users_api import router as users_router
from payments_api import router as payments_router
from nuvei_webhook import router as nuvei_router

# Inicialización de base de datos
from database import init_db


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


