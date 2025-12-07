# ============================================================
# users_api.py — Gestión de usuarios para PostgreSQL (Render)
# PITIUPI v5.0 — Arquitectura Backend + Bot Telegram
# ============================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from database import get_connection
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# MODELO Pydantic
# ============================================================
class UserRegister(BaseModel):
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    city: str | None = None
    document_number: str | None = None

    @validator("*", pre=True)
    def empty_to_none(cls, v):
        """Evita insertar cadenas vacías en PostgreSQL."""
        if v == "" or v is None:
            return None
        return v


# ============================================================
# REGISTRO / ACTUALIZACIÓN DE USUARIO
# ============================================================
@router.post("/register")
def register_user(data: UserRegister):

    logger.info(f"📥 Recibido registro usuario: {data.telegram_id}")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users (
                telegram_id,
                telegram_first_name,
                telegram_last_name,
                email,
                phone,
                country,
                city,
                document_number,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                telegram_first_name = COALESCE(EXCLUDED.telegram_first_name, users.telegram_first_name),
                telegram_last_name  = COALESCE(EXCLUDED.telegram_last_name, users.telegram_last_name),
                email               = COALESCE(EXCLUDED.email, users.email),
                phone               = COALESCE(EXCLUDED.phone, users.phone),
                country             = COALESCE(EXCLUDED.country, users.country),
                city                = COALESCE(EXCLUDED.city, users.city),
                document_number     = COALESCE(EXCLUDED.document_number, users.document_number)
            RETURNING id,
                      telegram_id,
                      telegram_first_name,
                      telegram_last_name,
                      email,
                      phone,
                      country,
                      city,
                      document_number,
                      created_at;
        """, (
            data.telegram_id,
            data.first_name,
            data.last_name,
            data.email,
            data.phone,
            data.country,
            data.city,
            data.document_number
        ))

        user_row = cursor.fetchone()
        conn.commit()

        logger.info(f"✅ Usuario sincronizado con éxito (ID {user_row['id']})")

        return {
            "success": True,
            "user": user_row
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error registrando usuario: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando usuario en PostgreSQL: {str(e)}"
        )

    finally:
        conn.close()
