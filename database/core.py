# ✅ database/core.py — Núcleo de la base de datos — PITIUPI V6.3 (CORREGIDO)
# PostgreSQL único (Render) + Importación segura de todos los modelos
# Corrección crítica: Resolución de dependencias circulares para WithdrawalRequest
# ============================================================

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
# IMPORTACIÓN SEGURA DE MODELOS (CRÍTICO PARA RELACIONES)
# -------------------------------------------------
# Esta sección asegura que todos los modelos se importen ANTES
# de que SQLAlchemy intente resolver las relaciones circulares
# como User <-> WithdrawalRequest

logger.info("📥 Iniciando importación segura de modelos...")

# ✅ Importación ordenada para resolver dependencias circulares
try:
    # Importar modelos en orden de dependencia
    from database.models.base import Base  # Base debe importarse primero
    
    # Modelos principales (sin dependencias cruzadas)
    from database.models.user import User
    from database.models.transaction import Transaction
    from database.models.payment_intents import PaymentIntent
    
    # Modelos dependientes (que referencian otros modelos)
    from database.models.withdrawals import WithdrawalRequest
    
    logger.info("✅ Todos los modelos importados correctamente")
    
except ImportError as e:
    logger.warning(f"⚠️ Advertencia de importación (opcional): {e}")
    # En algunos casos, ciertos modelos pueden ser opcionales
    # pero los principales (User, PaymentIntent) deben estar disponibles


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
    - sslmode: require (obligatorio para Neon/Render)
    
    Returns:
        Engine de SQLAlchemy configurado
    """
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Detecta conexiones muertas antes de usarlas
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # Debug SQL
        future=True,  # SQLAlchemy 2.0 style
        connect_args={
            "sslmode": "require",  # Requerido para Neon/Render
            "connect_timeout": 10   # Timeout de conexión
        }
    )


# Inicializar engine global
sync_engine: Engine = create_sync_engine()
logger.info("✅ sync_engine inicializado correctamente")


# -------------------------------------------------
# VERIFICACIÓN DE CONEXIÓN (OPCIONAL PERO RECOMENDADO)
# -------------------------------------------------
def verify_database_connection():
    """
    Verifica que la conexión a la base de datos funcione correctamente.
    
    Returns:
        bool: True si la conexión es exitosa
    """
    try:
        with sync_engine.connect() as conn:
            conn.execute("SELECT 1")
        logger.info("✅ Conexión a la base de datos verificada")
        return True
    except Exception as e:
        logger.error(f"❌ Error verificando conexión a la base de datos: {e}")
        return False


# Verificar conexión al iniciar (solo en desarrollo)
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
