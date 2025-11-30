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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_intents (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount NUMERIC(10,2) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',     -- pending / paid / failed
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                paid_at TIMESTAMP NULL,

                -- Datos específicos de Nuvei
                transaction_id VARCHAR(255),        -- providerTransactionId
                authorization_code VARCHAR(255),    -- Authorization code
                status_detail INTEGER,              -- Nuvei status_detail (3 = approved)
                order_id VARCHAR(255)               -- LinkToPay order.id
            );
        """)

        conn.commit()
        logger.info("Base de datos inicializada correctamente")
    except Exception as e:
        logger.error(f"Error inicializando BD: {str(e)}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
