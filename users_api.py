# ============================================================
# users_api.py — Gestión de usuarios PostgreSQL (Render)
# PITIUPI v5.1 — Backend oficial (BALANCE ACTIVADO)
# ============================================================

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from database import get_connection
import logging

router = APIRouter(tags=["users"])
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
        """Evita insertar strings vacíos en PostgreSQL."""
        if v == "" or v is None:
            return None
        return v


# ============================================================
# POST /users/register
# Registrar o actualizar usuario (NO toca balance)
# ============================================================

@router.post("/register")
def register_user(data: UserRegister):
    logger.info(f"📥 Registro usuario TelegramID={data.telegram_id}")

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
            RETURNING
                id,
                telegram_id,
                telegram_first_name AS first_name,
                telegram_last_name  AS last_name,
                email,
                phone,
                country,
                city,
                document_number,
                balance,
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

        user = cursor.fetchone()
        conn.commit()

        return {"success": True, "user": user}

    except Exception as e:
        conn.rollback()
        logger.error("❌ Error registrando usuario", exc_info=True)
        raise HTTPException(500, f"Error registrando usuario: {str(e)}")

    finally:
        conn.close()


# ============================================================
# GET /users/{telegram_id}
# Obtener usuario + BALANCE REAL
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
                telegram_last_name  AS last_name,
                email,
                phone,
                country,
                city,
                document_number,
                balance,
                created_at,
                updated_at
            FROM users
            WHERE telegram_id = %s
            LIMIT 1;
        """, (telegram_id,))

        user = cursor.fetchone()

        if not user:
            raise HTTPException(404, "Usuario no encontrado")

        return {"success": True, "user": user}

    except HTTPException:
        raise

    except Exception as e:
        logger.error("❌ Error obteniendo usuario", exc_info=True)
        raise HTTPException(500, f"Error interno consultando usuario: {str(e)}")

    finally:
        conn.close()


# ============================================================
# DELETE /users/{telegram_id}
# Eliminar usuario COMPLETO
# ============================================================

@router.delete("/{telegram_id}")
def delete_user(telegram_id: int):
    logger.warning(f"🗑 Eliminando usuario {telegram_id}")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id FROM users WHERE telegram_id = %s LIMIT 1;",
            (telegram_id,)
        )
        row = cursor.fetchone()

        if not row:
            return {"success": False, "detail": "Usuario no existe"}

        user_id = row["id"]

        # Eliminar dependencias reales
        cursor.execute("DELETE FROM payment_intents WHERE user_id = %s;", (user_id,))
        cursor.execute("DELETE FROM transactions_log WHERE user_id = %s;", (user_id,))
        cursor.execute("""
            DELETE FROM challenges
            WHERE challenger_id = %s OR opponent_id = %s;
        """, (user_id, user_id))
        cursor.execute("DELETE FROM tournaments WHERE owner_id = %s;", (user_id,))

        # Eliminar usuario
        cursor.execute(
            "DELETE FROM users WHERE id = %s RETURNING id;",
            (user_id,)
        )

        conn.commit()
        return {"success": True, "deleted": telegram_id}

    except Exception as e:
        conn.rollback()
        logger.error("❌ Error eliminando usuario", exc_info=True)
        raise HTTPException(500, f"Error eliminando usuario: {str(e)}")

    finally:
        conn.close()

