# ============================================================
# database/__init__.py
# Paquete database (LIVIANO, sin efectos secundarios)
# PITIUPI v5.0
# ============================================================

"""
IMPORTANTE:
Este __init__ NO debe inicializar engines automáticamente.

- Para engines: usa `from database.core import sync_engine, async_engine`
- Para sesiones: usa `from database.session import db_session, async_db_session`
- Para modelos: usa `from database.models import Base`
"""

__all__ = []
