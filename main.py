from fastapi import FastAPI
from nuvei_webhook import router as nuvei_router
from database import init_db

app = FastAPI(
    title="Pitiupi Backend",
    description="Backend con integración Nuvei LinkToPay",
    version="1.0.0"
)

# Inicializar base de datos
init_db()

# Rutas del webhook
app.include_router(nuvei_router)


@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Pitiupi Backend listo"
    }
