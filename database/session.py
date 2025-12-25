# ==========================================
# database/session.py
# Manejo de sesiones SQLAlchemy
# PITIUPI V6 — Sync únicamente
# La infraestructura NO hace commit
# ==========================================

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session, sessionmaker

from database.core import sync_engine

logger = logging.getLogger("database.session")


# =====================================================
# SESSION FACTORY (SYNC) — ÚNICA FUENTE DE VERDAD
# =====================================================

SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # Permite acceder a objetos después del commit
)


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """
    Context manager para sesiones de base de datos.
    
    ⚠️ IMPORTANTE — REGLA V6:
    Este context manager NO hace commit automático.
    El caller (normalmente un Service) es responsable de:
    - Decidir cuándo hacer commit()
    - Manejar la lógica transaccional
    - Validar que la operación es segura
    
    La infraestructura solo garantiza:
    - Rollback automático en caso de excepción
    - Cierre seguro de la sesión
    
    Uso correcto (Service):
        with db_session() as session:
            # 1. Ejecutar CRUDs
            user_crud.update_balance(session, user_id, -100)
            transaction_crud.create(session, ...)
            
            # 2. Validar que todo está OK
            if not validate_operation(...):
                raise ValueError("Operación inválida")
            
            # 3. Service decide hacer commit
            session.commit()
    
    Uso INCORRECTO:
        with db_session() as session:
            user_crud.update_balance(session, user_id, -100)
            # ❌ NO hay commit — cambios se pierden
    
    Yields:
        Session: Sesión de SQLAlchemy lista para usar
        
    Raises:
        Exception: Cualquier error de la operación (después de rollback)
    """
    session = SessionLocal()
    try:
        yield session
    except Exception as e:
        session.rollback()
        logger.error(f"❌ Error en sesión — rollback automático: {e}", exc_info=True)
        raise
    finally:
        session.close()
        logger.debug("🔒 Sesión cerrada")


def get_session() -> Session:
    """
    Crea una sesión manual (sin context manager).
    
    ⚠️ IMPORTANTE: El llamador es responsable de:
    - Hacer commit/rollback según la lógica de negocio
    - Cerrar la sesión con session.close()
    
    Uso principal: FastAPI dependencies
    
    Ejemplo con FastAPI:
        from database.session import get_session
        from fastapi import Depends
        
        def get_db():
            db = get_session()
            try:
                yield db
                # FastAPI NO hace commit automático
                # Los endpoints deben hacerlo explícitamente
            finally:
                db.close()
        
        @app.post("/users")
        def create_user(data: UserCreate, db: Session = Depends(get_db)):
            user = user_crud.create_user(db, data)
            db.commit()  # ✅ Commit explícito en el endpoint
            return user
    
    Returns:
        Session: Nueva sesión de SQLAlchemy
    """
    return SessionLocal()


# =====================================================
# EXPORTACIONES PÚBLICAS
# =====================================================

__all__ = [
    "SessionLocal",
    "db_session",
    "get_session",
]
