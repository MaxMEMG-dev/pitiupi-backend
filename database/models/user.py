# ============================================================
# database/models/user.py
# Modelo principal de usuario PITIUPI v6.0
# ✅ CORREGIDO: Lazy loading para evitar imports circulares
# ============================================================

import uuid
from decimal import Decimal
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Numeric, Text,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship, validates

# ✅ Import consistente
from database.models.base import Base, TimestampMixin
from database.types import UUIDType, JSONType


class UserStatus:
    ACTIVE = "active"
    PENDING = "pending"
    BANNED = "banned"
    SUSPENDED = "suspended"


class User(Base, TimestampMixin):
    """
    Modelo principal de usuario. 
    Single Source of Truth para la identidad y el estado financiero actual.
    """
    __tablename__ = "users"

    # --------------------------------------------------------
    # Identidad y Telegram
    # --------------------------------------------------------
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(UUIDType, default=uuid.uuid4, unique=True, nullable=False)
    
    telegram_id = Column(String(64), unique=True, nullable=False, index=True)
    telegram_username = Column(String(64), index=True, nullable=True)
    telegram_first_name = Column(String(128), nullable=True)
    telegram_last_name = Column(String(128), nullable=True)

    # --------------------------------------------------------
    # Estado y Configuración
    # --------------------------------------------------------
    status = Column(String(32), default=UserStatus.PENDING, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    lang = Column(String(2), default="es", nullable=False)  # 'es' o 'en'

    # --------------------------------------------------------
    # Balance (Mantenido por users_service mediante FOR UPDATE)
    # --------------------------------------------------------
    balance_available = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    balance_locked = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    balance_total = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)

    # --------------------------------------------------------
    # Datos de Registro / Onboarding (Milestone #1)
    # --------------------------------------------------------
    email = Column(String(255), nullable=True, unique=True)
    phone = Column(String(32), nullable=True)
    country = Column(String(64), nullable=True)
    city = Column(String(128), nullable=True)
    document_number = Column(String(64), nullable=True)
    birthdate = Column(String(32), nullable=True)  # Formato "YYYY-MM-DD"
    
    terms_accepted = Column(Boolean, default=False, nullable=False)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    
    first_deposit_completed = Column(Boolean, default=False, nullable=False)
    first_deposit_at = Column(DateTime(timezone=True), nullable=True)

    # --------------------------------------------------------
    # KYC y Métricas
    # --------------------------------------------------------
    kyc_status = Column(String(32), default="pending")
    total_deposits = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    total_wins = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)

    # --------------------------------------------------------
    # Seguridad y Preferencias
    # --------------------------------------------------------
    settings = Column(JSONType, default=dict, nullable=False)
    preferences = Column(JSONType, default=dict, nullable=False)
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # --------------------------------------------------------
    # Relaciones (Ajustadas para V6 - Lazy Loading)
    # --------------------------------------------------------
    # ✅ CORREGIDO: Usar string reference + lazy='dynamic' para evitar circular imports
    transactions = relationship(
        "Transaction",  # String reference - resuelto en runtime
        back_populates="user",
        cascade="save-update, merge",  # V6: No borrar ledger
        lazy="dynamic",  # ✅ Evita cargar todas las transacciones automáticamente
        order_by="Transaction.created_at.desc()"  # ✅ Ordenar por más reciente
    )
    
    # ✅ AGREGADO: Relación con PaymentIntents (lazy loading)
    payment_intents = relationship(
        "PaymentIntent",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",  # ✅ Carga bajo demanda
        order_by="PaymentIntent.created_at.desc()"
    )
    
    # Relaciones de retos (lazy loading)
    challenges_as_challenger = relationship(
        "Challenge",
        foreign_keys="Challenge.challenger_id",
        back_populates="challenger",
        lazy="dynamic"  # ✅ Evita N+1 queries
    )

    challenges_as_opponent = relationship(
        "Challenge",
        foreign_keys="Challenge.opponent_id",
        back_populates="opponent",
        lazy="dynamic"  # ✅ Evita N+1 queries
    )

    # --------------------------------------------------------
    # Índices y Table Args
    # --------------------------------------------------------
    __table_args__ = (
        Index("idx_users_telegram_id", "telegram_id", unique=True),
        Index("idx_users_uuid", "uuid", unique=True),
        Index("idx_users_status", "status"),
        Index("idx_users_lang", "lang"),
        Index("idx_users_email", "email", unique=True),
        Index("idx_users_status_lang", "status", "lang"),  # ✅ Query común
    )

    # --------------------------------------------------------
    # Validaciones y Helpers
    # --------------------------------------------------------
    @validates("balance_available", "balance_locked")
    def validate_balance(self, key, value):
        if value is not None and Decimal(str(value)) < Decimal("0.00"):
            raise ValueError(f"{key} no puede ser negativo")
        return value

    @validates("lang")
    def validate_lang(self, key, value):
        if value not in ["es", "en"]:
            raise ValueError("Idioma debe ser 'es' o 'en'")
        return value

    def recalculate_total(self):
        """Helper para actualizar balance_total antes de commit."""
        self.balance_total = self.balance_available + self.balance_locked

    def to_dict(self):
        """Serialización para API interna."""
        return {
            "uuid": str(self.uuid),
            "telegram_id": self.telegram_id,
            "telegram_username": self.telegram_username,
            "status": self.status,
            "lang": self.lang,
            "balance": {
                "available": float(self.balance_available),
                "locked": float(self.balance_locked),
                "total": float(self.balance_total)
            },
            "is_profile_complete": self.is_profile_complete,
            "email": self.email,
            "phone": self.phone,
            "country": self.country,
            "city": self.city
        }

    @property
    def is_profile_complete(self) -> bool:
        """
        Lógica central de Onboarding V6.
        Define si el usuario puede operar/pagar.
        """
        required = [
            self.telegram_first_name,
            self.country,
            self.city,
            self.document_number,
            self.birthdate,
            self.email,
            self.phone
        ]
        return all(field is not None and str(field).strip() != "" for field in required)
    
    @property
    def display_name(self) -> str:
        """Nombre para mostrar en UI"""
        if self.telegram_first_name:
            full_name = self.telegram_first_name
            if self.telegram_last_name:
                full_name += f" {self.telegram_last_name}"
            return full_name
        return self.telegram_username or f"Usuario {self.telegram_id}"

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, telegram_id={self.telegram_id}, "
            f"status={self.status}, lang={self.lang})>"
        )
