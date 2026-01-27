# ============================================================
# main.py — PITIUPI Backend Stripe
# PITIUPI v6.4 — Migración a Stripe
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import sys
import os

# IMPORTAR NUEVOS ROUTERS
from payments_api import router as payments_router
from stripe_webhook import router as stripe_router

# Configuración Logs
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("pitiupi-backend")

app = FastAPI(title="PITIUPI Backend Stripe", version="6.4.0")

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
# Nota: La URL del webhook en Stripe Dashboard será: 
# https://tu-dominio.com/webhooks/stripe/callback

@app.get("/")
def root():
    return {"service": "PITIUPI Backend Stripe", "status": "running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

