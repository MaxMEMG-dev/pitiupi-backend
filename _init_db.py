# _init_db.py
import psycopg2
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,

    telegram_first_name VARCHAR(100),
    telegram_last_name VARCHAR(100),

    email VARCHAR(255),
    phone VARCHAR(50),

    country VARCHAR(100),
    city VARCHAR(100),

    document_number VARCHAR(100),

    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

PAYMENT_INTENTS_SQL = """
CREATE TABLE IF NOT EXISTS payment_intents (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMP NULL,

    transaction_id VARCHAR(255),
    authorization_code VARCHAR(255),
    status_detail INTEGER,
    order_id VARCHAR(255)
);
"""

def run_migrations():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        logger.info("🛠 Creando tabla users si no existe...")
        cur.execute(USERS_TABLE_SQL)

        logger.info("🛠 Creando tabla payment_intents si no existe...")
        cur.execute(PAYMENT_INTENTS_SQL)

        conn.commit()
        conn.close()
        logger.info("✅ Migraciones completadas con éxito")

    except Exception as e:
        logger.error(f"❌ Error ejecutando migraciones: {e}")
        raise

