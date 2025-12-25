# ============================================================
# database/models/base.py — PITIUPI v5.0
# Base declarativa y mixins comunes (independiente de engines)
# ============================================================

from datetime import datetime, timezone
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, DateTime


def _utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarativa para todos los modelos."""
    pass


class TimestampMixin:
    """Campos estándar de auditoría."""
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
