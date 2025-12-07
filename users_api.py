from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_connection
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class UserRegister(BaseModel):
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    city: str | None = None
    document_number: str | None = None


@router.post("/register")
def register_user(data: UserRegister):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users (
                telegram_id, telegram_first_name, telegram_last_name,
                email, phone, country, city, document_number
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                telegram_first_name = EXCLUDED.telegram_first_name,
                telegram_last_name  = EXCLUDED.telegram_last_name,
                email               = EXCLUDED.email,
                phone               = EXCLUDED.phone,
                country             = EXCLUDED.country,
                city                = EXCLUDED.city,
                document_number     = EXCLUDED.document_number
            RETURNING id;
        """, (
            data.telegram_id,
            data.first_name,
            data.last_name,
            data.email,
            data.phone,
            data.country,
            data.city,
            data.document_number,
        ))

        row = cursor.fetchone()
        conn.commit()

        return {"success": True, "user_id": row["id"]}

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error registrando usuario: {e}")
        raise HTTPException(status_code=500, detail="Error registrando usuario en PostgreSQL")

    finally:
        conn.close()
