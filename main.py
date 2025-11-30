from fastapi import FastAPI
from database import init_db
from nuvei_webhook import router as nuvei_router
from payments_api import router as payments_router
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Pitiupi Backend",
    description="Backend con integración Nuvei LinkToPay",
    version="1.0.0"
)

# Inicializar base de datos
init_db()

# Registrar rutas
app.include_router(nuvei_router)
app.include_router(payments_router)

@app.get("/")
def home():
    return {"status": "running", "message": "Pitiupi Backend listo"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": "2024-01-01T00:00:00Z"}
