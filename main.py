from fastapi import FastAPI
from nuvei_webhook import router as nuvei_router
from database import init_db

app = FastAPI(
    title="Pitiupi Backend",
    version="1.0",
    description="Backend para manejo de pagos Nuvei LinkToPay"
)

# Inicializar la base de datos
init_db()

# Registrar rutas del webhook
app.include_router(nuvei_router)


@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Pitiupi Backend listo"
    }
