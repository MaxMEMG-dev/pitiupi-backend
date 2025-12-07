from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_connection
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class UserRegister(BaseModel):
    telegram_id: int
    first_name: str
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

    # Verificar si ya existe
    cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (data.telegram_id,))
    found = cursor.fetchone()

    if found:
        return {"status": "exists"}

    # Insertar usuario
    cursor.execute("""
        INSERT INTO users (
            telegram_id, first_name, last_name,
            email, phone, country, city, document_number
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id;
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

    user_id = cursor.fetchone()["id"]
    conn.commit()

    return {"status": "created", "id": user_id}
