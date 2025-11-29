# Pitiupi Backend — FastAPI + Nuvei LinkToPay

Este es el backend oficial del proyecto **Pitiupi**, diseñado para procesar pagos
reales mediante **Nuvei (Paymentez Ecuador)** usando **LinkToPay**.

Incluye:
- Webhook Nuvei real
- Generación de LinkToPay desde cualquier cliente (bot, web, app)
- Validación de pagos (`status=success`, `status_detail=3`)
- Actualización de intents en SQLite
- Despliegue automático en Render.com

## 🚀 Tecnologías

- Python 3.10+
- FastAPI
- Uvicorn
- SQLite
- Nuvei LinkToPay API
- Requests

## 📦 Estructura del proyecto

pitiupi-backend/
│
├── main.py → Servidor FastAPI principal
├── nuvei_webhook.py → Webhook Nuvei (callback oficial)
├── nuvei_client.py → Cliente para consumir LinkToPay
├── payments_core.py → Lógica interna de intents
├── database.py → Conexión SQLite
├── settings.py → Variables de entorno / Configuración
├── requirements.txt → Dependencias
└── Procfile → Comando para despliegue (opcional)

## 🔑 Variables de entorno

Render → Environment → Add Environment Variable:

NUVEI_APP_CODE_SERVER=LINKTOPAY01-EC-SERVER
NUVEI_APP_KEY_SERVER=G8vwvaASAZHQgoVuF2eKZyZF5hJmvx
NUVEI_ENV=stg
DB_PATH=database.db

## ▶ Ejecutar localmente

Crear entorno:

pip install -r requirements.txt
uvicorn main:app --reload
