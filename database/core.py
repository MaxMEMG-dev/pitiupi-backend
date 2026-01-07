# ✅ database/core.py — Núcleo de la base de datos — PITIUPI V6.3 (CORREGIDO)
# ✅ SOLUCIÓN: Configuración tardía de relaciones para evitar ciclos
# ============================================================

import os
import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import relationship

logger = logging.getLogger("database.core")
logger.setLevel(logging.INFO)


def _sanitize_db_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.hostname or "unknown"
        user = p.username or "unknown"
        db = (p.path or "").lstrip("/") or "unknown"
        scheme = p.scheme
        return f"{scheme}://{user}:***@{host}/{db}"
    except Exception:
        return "<invalid-db-url>"


# -------------------------------------------------
# CONFIGURACIÓN DE BASE DE DATOS
# -------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL no está definida.")
    raise RuntimeError("DATABASE_URL es obligatoria")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    logger.info("🔄 Normalizado postgres:// → postgresql://")

if not DATABASE_URL.startswith("postgresql://"):
    logger.error(f"❌ URL inválida: {_sanitize_db_url(DATABASE_URL)}")
    raise RuntimeError("PITIUPI V6 solo soporta PostgreSQL")

logger.info(f"🔗 DATABASE_URL detectada: {_sanitize_db_url(DATABASE_URL)}")


# -------------------------------------------------
# ✅ IMPORTACIÓN SEGURA DE MODELOS (SIN CICLOS)
# -------------------------------------------------

logger.info("📥 Iniciando importación segura de modelos...")

try:
    # 1. Importar Base primero
    from database.models.base import Base
    
    # 2. Importar modelos básicos (sin relaciones circulares)
    from database.models.user import User
    from database.models.transactions import Transaction
    from database.models.payment_intents import PaymentIntent
    from database.models.challenges import Challenge
    
    logger.info("✅ Modelos principales importados correctamente")
    
except ImportError as e:
    logger.warning(f"⚠️ Advertencia de importación: {e}")


# -------------------------------------------------
# ENGINE SÍNCRONO
# -------------------------------------------------

def create_sync_engine() -> Engine:
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        future=True,
        connect_args={
            "sslmode": "prefer",
            "connect_timeout": 10
        }
    )


sync_engine: Engine = create_sync_engine()
logger.info("✅ sync_engine inicializado correctamente")


# -------------------------------------------------
# ✅ CONFIGURACIÓN TARDÍA DE RELACIONES
# -------------------------------------------------
def configure_relationships():
    """
    Configura relaciones circulares después de importar todos los modelos.
    Esto evita errores de importación circular.
    """
    logger.info("🔗 Configurando relaciones entre modelos...")
    
    try:
        # ✅ Importar WithdrawalRequest ahora que User ya está importado
        from database.models.withdrawals import WithdrawalRequest
        
        # Configurar relación en User
        User.withdrawal_requests = relationship(
            "WithdrawalRequest",
            foreign_keys="[WithdrawalRequest.user_id]",
            back_populates="user",
            lazy="dynamic",
            order_by="WithdrawalRequest.created_at.desc()"
        )
        
        # Re-configurar relación en WithdrawalRequest
        WithdrawalRequest.user = relationship(
            "User",
            foreign_keys=[WithdrawalRequest.user_id],
            back_populates="withdrawal_requests"
        )
        
        logger.info("✅ Relaciones configuradas correctamente")
        
    except Exception as e:
        logger.error(f"❌ Error configurando relaciones: {e}")
        raise


# Ejecutar configuración de relaciones
configure_relationships()


# -------------------------------------------------
# VERIFICACIÓN DE CONEXIÓN
# -------------------------------------------------
def verify_database_connection():
    """
    Verifica que la conexión a la base de datos funcione correctamente.
    
    Returns:
        bool: True si la conexión es exitosa
    """
    try:
        from sqlalchemy import text  # ✅ Importar text aquí
        
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))  # ✅ Usar text()
        logger.info("✅ Conexión a la base de datos verificada")
        return True
    except Exception as e:
        logger.error(f"❌ Error verificando conexión a la base de datos: {e}")
        return False


if os.getenv("ENV") != "production":
    verify_database_connection()


# -------------------------------------------------
# EXPORTACIONES PÚBLICAS
# -------------------------------------------------

__all__ = [
    "DATABASE_URL",
    "sync_engine",
    "verify_database_connection"
]
