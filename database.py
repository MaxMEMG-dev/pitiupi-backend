import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # ============================
        #   TABLA USERS (REQUIRED)
        # ============================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,

                telegram_first_name VARCHAR(100),
                telegram_last_name VARCHAR(100),
                email VARCHAR(200),
                phone VARCHAR(50),

                country VARCHAR(100),
                city VARCHAR(100),
                document_number VARCHAR(50),

                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # ============================
        #   TABLA PAYMENT INTENTS
        # ============================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_intents (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount NUMERIC(10,2) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                paid_at TIMESTAMP NULL,

                -- Datos específicos Nuvei
                transaction_id VARCHAR(255),
                authorization_code VARCHAR(255),
                status_detail INTEGER,
                order_id VARCHAR(255)
            );
        """)

        conn.commit()
        logger.info("Base de datos inicializada correctamente (users + payment_intents)")

    except Exception as e:
        logger.error(f"Error inicializando BD: {str(e)}")
        if conn:
            conn.rollback()
        raise

    finally:
        if conn:
            conn.close()
