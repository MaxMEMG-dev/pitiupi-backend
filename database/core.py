# ================================================
# database/core.py
# Núcleo de la base de datos — PITIUPI V6
# PostgreSQL únicamente (Render)
# Sin fallbacks, sin SQLite, sin async duplicado
# ================================================

import os
import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

logger = logging.getLogger("database.core")
logger.setLevel(logging.INFO)


def _sanitize_db_url(url: str) -> str:
    """
    Oculta la contraseña en los logs para seguridad.
    
    Args:
        url: URL de conexión a la base de datos
        
    Returns:
        URL sanitizada sin contraseña visible
    """
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

# Obtener URL desde variable de entorno
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL no está definida. Revisa tu configuración de Render.")
    raise RuntimeError(
        "DATABASE_URL es obligatoria en PITIUPI V6. "
        "Configúrala en Render → Dashboard → Environment."
    )

# Normalizar postgres:// -> postgresql:// (Render a veces usa el formato antiguo)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    logger.info("🔄 Normalizado postgres:// → postgresql://")

# Validar que sea PostgreSQL
if not DATABASE_URL.startswith("postgresql://"):
    logger.error(f"❌ URL inválida: {_sanitize_db_url(DATABASE_URL)}")
    raise RuntimeError(
        "PITIUPI V6 solo soporta PostgreSQL. "
        f"URL recibida: {_sanitize_db_url(DATABASE_URL)}"
    )

logger.info(f"🔗 DATABASE_URL detectada: {_sanitize_db_url(DATABASE_URL)}")


# -------------------------------------------------
# ENGINE SÍNCRONO (ÚNICA FUENTE DE VERDAD)
# -------------------------------------------------

def create_sync_engine() -> Engine:
    """
    Crea el engine síncrono de SQLAlchemy para PostgreSQL.
    
    Configuración optimizada para Render (Free/Starter):
    - pool_size: 5 conexiones simultáneas
    - max_overflow: 10 conexiones adicionales en picos
    - pool_pre_ping: verifica conexiones antes de usarlas
    
    Returns:
        Engine de SQLAlchemy configurado
    """
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Detecta conexiones muertas
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # Debug SQL
        future=True,  # SQLAlchemy 2.0 style
        connect_args={"sslmode": "require"}
    )


# Inicializar engine global
sync_engine: Engine = create_sync_engine()
logger.info("✅ sync_engine inicializado correctamente")


# -------------------------------------------------
# EXPORTACIONES PÚBLICAS
# -------------------------------------------------

__all__ = [
    "DATABASE_URL",
    "sync_engine",
]
