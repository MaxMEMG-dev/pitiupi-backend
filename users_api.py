# ============================================================
# users_api.py — Gestión de usuarios PostgreSQL (Render)
# PITIUPI v5.0 — Backend oficial
# ============================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from database import get_connection
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# MODELO Pydantic (sanitiza datos vacíos)
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
# POST /users/register → Registrar o actualizar usuario
# ============================================================
@router.post("/register")
def register_user(data: UserRegister):

    logger.info(f"📥 Recibido registro usuario TelegramID={data.telegram_id}")

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
                created_at,
                updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                telegram_first_name = COALESCE(EXCLUDED.telegram_first_name, users.telegram_first_name),
                telegram_last_name  = COALESCE(EXCLUDED.telegram_last_name, users.telegram_last_name),
                email               = COALESCE(EXCLUDED.email, users.email),
                phone               = COALESCE(EXCLUDED.phone, users.phone),
                country             = COALESCE(EXCLUDED.country, users.country),
                city                = COALESCE(EXCLUDED.city, users.city),
                document_number     = COALESCE(EXCLUDED.document_number, users.document_number),
                updated_at          = NOW()
            RETURNING id,
                      telegram_id,
                      telegram_first_name,
                      telegram_last_name,
                      email,
                      phone,
                      country,
                      city,
                      document_number,
                      created_at,
                      updated_at;
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

        logger.info(f"✅ Usuario sincronizado con éxito: ID={user_row['id']}")

        return {
            "success": True,
            "user": user_row
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error registrando usuario: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error registrando usuario en PostgreSQL"
        )

    finally:
        conn.close()


# ============================================================
# GET /users/{telegram_id} → Obtener usuario desde PostgreSQL
# ============================================================
@router.get("/{telegram_id}")
def get_user(telegram_id: int):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                id,
                telegram_id,
                telegram_first_name AS first_name,
                telegram_last_name AS last_name,
                email,
                phone,
                country,
                city,
                document_number,
                created_at,
                updated_at
            FROM users
            WHERE telegram_id = %s
            LIMIT 1;
        """, (telegram_id,))

        row = cursor.fetchone()

        if not row:
            logger.warning(f"⚠️ Usuario {telegram_id} NO encontrado en PostgreSQL")
            raise HTTPException(404, "Usuario no encontrado")

        return {"success": True, "user": row}

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error obteniendo usuario {telegram_id}: {e}", exc_info=True)
        raise HTTPException(500, "Error interno consultando usuario")

    finally:
        conn.close()

