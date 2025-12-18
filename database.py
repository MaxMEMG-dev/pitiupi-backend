# ============================================================
# database.py — Conexión PostgreSQL + Inicialización (BACKEND)
# PITIUPI v5.x — Backend estable compatible con BOT
# ============================================================

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ============================================================
# DATABASE URL (Render PostgreSQL)
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ ERROR: DATABASE_URL no está definida en variables de entorno")


# ============================================================
# Conexión PostgreSQL centralizada
# ============================================================

def get_connection():
    """
    Devuelve una conexión PostgreSQL con cursor dict.
    El backend NO gestiona sesiones persistentes.
    """
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        logger.error(f"❌ No se pudo conectar a PostgreSQL: {e}")
        raise


# ============================================================
# Inicialización de Base de Datos (SAFE MODE)
# ============================================================

def init_db():
    """
    Inicializa SOLO las tablas mínimas necesarias para el backend.
    Compatible con el esquema del bot.
    NO rompe si la DB ya existe.
    """
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()
        logger.info("🔗 Conexión PostgreSQL establecida")

        # ====================================================
        # TABLA USERS (alineada con BOT)
        # ====================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,

                telegram_username VARCHAR(100),
                telegram_first_name VARCHAR(100),
                telegram_last_name VARCHAR(100),

                email VARCHAR(200),
                phone VARCHAR(50),

                country VARCHAR(100),
                city VARCHAR(100),
                document_number VARCHAR(50),

                balance NUMERIC(12,2) DEFAULT 0.00,

                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)
        logger.info("🟢 Tabla 'users' verificada")

        # ====================================================
        # TABLA PAYMENT INTENTS (Nuvei)
        # ====================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_intents (
                id SERIAL PRIMARY KEY,

                user_id INTEGER,
                telegram_id BIGINT NOT NULL,

                amount NUMERIC(12,2) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                message TEXT,

                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                paid_at TIMESTAMP NULL,

                transaction_id VARCHAR(255),
                authorization_code VARCHAR(255),
                status_detail INTEGER,
                order_id VARCHAR(255)
            );
        """)
        logger.info("🟢 Tabla 'payment_intents' verificada")

        # ====================================================
        # ÍNDICES (seguros, idempotentes)
        # ====================================================
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id
            ON users(telegram_id);
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_intents_telegram_id
            ON payment_intents(telegram_id);
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_intents_order_id
            ON payment_intents(order_id);
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_intents_status
            ON payment_intents(status);
        """)

        conn.commit()
        logger.info("✅ Base de datos inicializada correctamente (backend)")

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error("❌ Error inicializando BD", exc_info=True)
        raise

    finally:
        if conn:
            conn.close()
            logger.info("🔒 Conexión PostgreSQL cerrada")
