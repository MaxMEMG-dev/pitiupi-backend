# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nuvei_webhook import router as nuvei_router
from payments_api import router as payments_router
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
    allow_methods=["*"],   # <- permite OPTIONS
    allow_headers=["*"],
)

# ----------------------------
# Inicializar base de datos
# ----------------------------
init_db()

# ----------------------------
# Registrar los routers
# ----------------------------
app.include_router(nuvei_router)
app.include_router(payments_router)

# ----------------------------
# Endpoint raíz
# ----------------------------
@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Pitiupi Backend listo"
    }



@app.get("/debug/nvuei")
def debug_nuvei():
    import os
    return {
        "NUVEI_APP_CODE_SERVER": os.getenv("NUVEI_APP_CODE_SERVER"),
        "NUVEI_APP_KEY_SERVER": os.getenv("NUVEI_APP_KEY_SERVER"),
        "NUVEI_ENV": os.getenv("NUVEI_ENV"),
    }

# ----------------------------
# Endpoint de estadísticas
# ----------------------------
from db import get_database_stats

@app.get("/stats")
def stats():
    """Devuelve estadísticas generales del sistema PITIUPI."""
    return get_database_stats()
