# ==========================================
# database/types.py
# Tipos personalizados para UUID y JSONB en PostgreSQL
# PITIUPI V6 — Exclusivo para PostgreSQL
# ==========================================

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.types import TypeDecorator


# ============================================================
# UUIDType — UUID nativo de PostgreSQL
# ============================================================
class UUIDType(TypeDecorator):
    """
    Columna UUID nativa de PostgreSQL.

    Características:
        - Almacenamiento eficiente (16 bytes vs 36 bytes de TEXT).
        - Indexación optimizada.
        - Validación automática a nivel de base de datos.
        - Conversión automática de strings válidos a UUID.

    Uso recomendado:
        id = Column(UUIDType, primary_key=True, default=uuid.uuid4)

    Beneficios frente a TEXT:
        - Menor uso de espacio (~56% menos).
        - Índices más rápidos.
        - Validación en DB (evita UUIDs inválidos).
    """

    impl = PG_UUID(as_uuid=True)
    cache_ok = True  # Permitir caché de instancias (seguro aquí)

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(PG_UUID(as_uuid=True))

    def process_bind_param(self, value: Any | None, dialect) -> uuid.UUID | None:
        """Convierte el valor antes de enviarlo a la base de datos."""
        if value is None:
            return None

        if isinstance(value, uuid.UUID):
            return value

        # Intentar convertir desde string u otros tipos representables
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Valor no convertible a UUID: {value!r}") from exc

    def process_result_value(self, value: uuid.UUID | None, dialect) -> uuid.UUID | None:
        """Devuelve el valor tal como lo entrega PostgreSQL (ya es uuid.UUID con as_uuid=True)."""
        return value


# ======================================
# JSONType — JSONB nativo de PostgreSQL
# ======================================
class JSONType(TypeDecorator):
    """
    Columna JSONB nativa de PostgreSQL.

    Características:
        - Almacenamiento binario optimizado (JSONB).
        - Soporte completo para operadores JSON (@>, ?|, ?&, etc.).
        - Indexación GIN eficiente.
        - Serialización automática de Decimal y UUID.

    Uso recomendado:
        config = Column(JSONType, nullable=False, default=dict)
        metadata = Column(JSONType, nullable=True)

    Beneficios frente a TEXT + json.dumps/loads:
        - Validación automática en DB.
        - Consultas avanzadas con operadores JSON.
        - Índices GIN para búsquedas rápidas.
        - Menor overhead de (de)serialización.
    """

    impl = PG_JSONB
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(PG_JSONB())

    def process_bind_param(self, value: Any | None, dialect) -> Any | None:
        """Serializa el valor a JSONB antes de guardarlo."""
        if value is None:
            return None

        try:
            return json.dumps(value, default=self._json_encoder, ensure_ascii=False)
        except TypeError as exc:
            raise TypeError(f"Objeto no serializable a JSON: {value!r}") from exc

    def process_result_value(self, value: Any | None, dialect) -> Any | None:
        """
        PostgreSQL con JSONB devuelve directamente dict/list cuando se usa el driver psycopg2/psycopg3.
        Este método es principalmente un safeguard.
        """
        return value

    @staticmethod
    def _json_encoder(obj: Any) -> Any:
        """Encoder personalizado para tipos no nativos de JSON."""
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, uuid.UUID):
            return str(obj)
        raise TypeError(f"Tipo no soportado en JSON: {type(obj).__name__}")


# ======================================
# EXPORTACIONES PÚBLICAS
# ======================================
__all__ = ["UUIDType", "JSONType"]
