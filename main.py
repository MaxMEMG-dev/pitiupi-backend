# ============================================================
# main.py — PITIUPI Backend Stripe
# PITIUPI v6.5 — Migración a Stripe + Users Sync API
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import sys
import os

# IMPORTAR ROUTERS
from payments_api import router as payments_router
from stripe_webhook import router as stripe_router
from users_api import router as users_router  # <--- NUEVA IMPORTACIÓN

# Configuración Logs
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("pitiupi-backend")

app = FastAPI(title="PITIUPI Backend Stripe", version="6.5.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# MONTAR ROUTERS
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(stripe_router, prefix="/webhooks/stripe", tags=["Stripe Webhook"])
app.include_router(users_router, prefix="/users", tags=["Users"]) # <--- ESTO ACTIVA LA RUTA /users

@app.get("/")
def root():
    return {"service": "PITIUPI Backend Stripe", "status": "running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
