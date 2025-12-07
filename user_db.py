import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")   # SOLO BACKEND PRODUCCIÓN
if not DB_URL:
    logger.error("❌ DATABASE_URL no está configurado en el backend")

# =============================================================
# CONEXIÓN
# =============================================================

def get_conn():
    """Conexión obligatoria a PostgreSQL (backend)."""
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)


# =============================================================
# OBTENER DATOS COMPLETOS DEL USUARIO (para Nuvei)
# =============================================================

def get_user_data(telegram_id: int):
    """
    Devuelve un dict con todos los datos del usuario necesarios
    para crear LinkToPay (según documentación Nuvei 2025).
    """

    query = """
        SELECT
            telegram_id,
            telegram_first_name AS first_name,
            telegram_last_name AS last_name,
            email,
            phone,
            country,
            city,
            document_number,
            created_at
        FROM users
        WHERE telegram_id = %s
        LIMIT 1;
    """

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(query, [telegram_id])
        row = cur.fetchone()
        conn.close()

        if not row:
            logger.warning(f"⚠️ Usuario {telegram_id} no existe en PostgreSQL")
            return None

        return row

    except Exception as e:
        logger.error(f"❌ Error obteniendo usuario {telegram_id}: {e}", exc_info=True)
        return None
