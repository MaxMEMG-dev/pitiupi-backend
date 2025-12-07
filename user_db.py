import os
import psycopg2
import sqlite3
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

DB_URL = os.getenv("BOT_DATABASE_URL") or os.getenv("DATABASE_URL")

USE_POSTGRES = DB_URL and DB_URL.startswith("postgres")
USE_SQLITE = not USE_POSTGRES

# -------------------------------------------------------------------
# FUNCIÓN DE CONEXIÓN
# -------------------------------------------------------------------

def get_conn():
    if USE_POSTGRES:
        return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    else:
        return sqlite3.connect("pitiupi.db")   # Path local del bot


# -------------------------------------------------------------------
# OBTENER DATOS COMPLETOS DEL USUARIO
# -------------------------------------------------------------------

def get_user_data(telegram_id: int):
    """
    Devuelve un dict con todos los datos requeridos por Nuvei:
    nombre, apellido, email, documento, ciudad, país, teléfono.
    """

    query = """
        SELECT
            telegram_first_name AS first_name,
            telegram_last_name AS last_name,
            email,
            phone,
            country,
            city,
            document_number
        FROM users
        WHERE telegram_id = %s
        LIMIT 1;
    """

    try:
        conn = get_conn()
        cur = conn.cursor()

        if USE_SQLITE:
            cur.execute(query.replace("%s", "?"), [telegram_id])
        else:
            cur.execute(query, [telegram_id])

        row = cur.fetchone()
        conn.close()

        if not row:
            return None

        # Convertir sqlite tuple -> dict
        if USE_SQLITE and not isinstance(row, dict):
            columns = [col[0] for col in cur.description]
            row = dict(zip(columns, row))

        return row

    except Exception as e:
        logger.error(f"❌ Error obteniendo usuario {telegram_id}: {e}")
        return None
