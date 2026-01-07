# ============================================================
# database/models/user.py - Modelo principal de usuario PITIUPI v6.2
# ✅ CORREGIDO: Eliminada importación circular con withdrawals.py
# ============================================================

import uuid
from decimal import Decimal
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Numeric, Text,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship, validates

from database.models.base import Base, TimestampMixin


class UserStatus:
    """Estados del usuario en el sistema"""
    PENDING = "pending_approval"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    REJECTED = "rejected"
    BANNED = "banned"
    SUSPENDED = "suspended"


class User(Base, TimestampMixin):
    """
    Modelo principal de usuario con KYC manual.
    ✅ CORREGIDO: Sin dependencias circulares
    """
    __tablename__ = "users"

    # --------------------------------------------------------
    # Identidad Básica y Telegram
    # --------------------------------------------------------
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False)
    
    telegram_id = Column(String(64), unique=True, nullable=False, index=True)
    telegram_username = Column(String(64), index=True, nullable=True)
    telegram_first_name = Column(String(128), nullable=True)
    telegram_last_name = Column(String(128), nullable=True)

    # --------------------------------------------------------
    # Datos de Identidad Completos (KYC)
    # --------------------------------------------------------
    first_name = Column(String(128), nullable=True)
    middle_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    second_last_name = Column(String(128), nullable=True)
    
    document_number = Column(String(64), nullable=True)
    birthdate = Column(String(32), nullable=True)
    email = Column(String(255), nullable=True, unique=True)
    
    country_code = Column(String(10), nullable=True)
    phone = Column(String(32), nullable=True)
    
    country = Column(String(64), nullable=True)
    city = Column(String(128), nullable=True)

    # --------------------------------------------------------
    # URLs de Documentos KYC
    # --------------------------------------------------------
    document_front_url = Column(Text, nullable=True)
    document_back_url = Column(Text, nullable=True)
    selfie_url = Column(Text, nullable=True)
    
    rejection_reason = Column(String(500), nullable=True)

    # --------------------------------------------------------
    # Estado y Verificación
    # --------------------------------------------------------
    status = Column(
        String(32), 
        default=UserStatus.PENDING_APPROVAL,
        nullable=False
    )
    is_admin = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    lang = Column(String(2), default="es", nullable=False)

    # --------------------------------------------------------
    # Balance
    # --------------------------------------------------------
    balance_recharge = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    balance_withdrawable = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    balance_locked = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    balance_total = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)

    # --------------------------------------------------------
    # Datos de Registro / Onboarding
    # --------------------------------------------------------
    terms_accepted = Column(Boolean, nullable=False, server_default="false")
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    
    registration_completed = Column(Boolean, nullable=False, server_default="false")
    first_deposit_made = Column(Boolean, nullable=False, server_default="false")
    first_deposit_amount = Column(Numeric(10, 2), nullable=True)
    first_deposit_date = Column(DateTime, nullable=True)
    
    # --------------------------------------------------------
    # KYC y Métricas
    # --------------------------------------------------------
    kyc_status = Column(String(32), nullable=True, server_default="pending")
    kyc_submitted_at = Column(DateTime, nullable=True)
    kyc_approved_at = Column(DateTime, nullable=True)
    kyc_rejected_at = Column(DateTime, nullable=True)
    
    total_deposits = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    total_wins = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)

    # --------------------------------------------------------
    # Seguridad y Preferencias
    # --------------------------------------------------------
    settings = Column(Text, default="{}", nullable=False)
    preferences = Column(Text, default="{}", nullable=False)
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # --------------------------------------------------------
    # ✅ RELACIONES CORREGIDAS: Sin dependencias circulares
    # --------------------------------------------------------
    
    # Relación con transactions
    transactions = relationship(
        "Transaction",
        back_populates="user",
        lazy="dynamic",
        order_by="Transaction.created_at.desc()"
    )
    
    # Relación con payment_intents
    payment_intents = relationship(
        "PaymentIntent",
        back_populates="user",
        lazy="dynamic",
        order_by="PaymentIntent.created_at.desc()"
    )
    
    # ✅ RELACIÓN CON WITHDRAWALS - IMPORTACIÓN TARDÍA
    # Esta relación se configura dinámicamente en database/core.py
    # withdrawal_requests = relationship(...) <- Configurado en database/session.py
    
    # --------------------------------------------------------
    # Índices
    # --------------------------------------------------------
    __table_args__ = (
        Index("idx_users_telegram_id", "telegram_id", unique=True),
        Index("idx_users_uuid", "uuid", unique=True),
        Index("idx_users_status", "status"),
        Index("idx_users_lang", "lang"),
        Index("idx_users_email", "email", unique=True),
        Index("idx_users_status_lang", "status", "lang"),
        Index("idx_users_is_verified", "is_verified"),
    )

    # --------------------------------------------------------
    # Métodos y propiedades
    # --------------------------------------------------------
    @validates("balance_recharge", "balance_withdrawable", "balance_locked")
    def validate_balance(self, key, value):
        if value is not None and Decimal(str(value)) < Decimal("0.00"):
            raise ValueError(f"{key} no puede ser negativo")
        return value

    @validates("lang")
    def validate_lang(self, key, value):
        if value is None:
            return None
        if value not in ["es", "en"]:
            raise ValueError("Idioma debe ser 'es' o 'en'")
        return value

    @validates("status")
    def validate_status(self, key, value):
        valid_statuses = [
            UserStatus.PENDING_APPROVAL,
            UserStatus.ACTIVE,
            UserStatus.REJECTED,
            UserStatus.BANNED,
            UserStatus.SUSPENDED
        ]
        if value not in valid_statuses:
            raise ValueError(f"Estado inválido: {value}")
        return value

    def recalculate_total(self):
        """Actualizar balance_total antes de commit."""
        self.balance_total = self.balance_recharge + self.balance_withdrawable + self.balance_locked

    @property
    def balance_available(self):
        return self.balance_recharge + self.balance_withdrawable

    @property
    def can_access_menu(self) -> bool:
        return (
            self.status == UserStatus.ACTIVE and 
            self.is_verified and 
            self.registration_completed and
            self.first_deposit_made
        )

    @property
    def is_profile_complete(self) -> bool:
        names_complete = all([
            self.first_name and self.first_name.strip(),
            self.last_name and self.last_name.strip()
        ])
        
        identity_complete = all([
            self.document_number and self.document_number.strip(),
            self.birthdate and self.birthdate.strip(),
            self.email and self.email.strip(),
            self.country_code and self.country_code.strip(),
            self.phone and self.phone.strip(),
            self.country and self.country.strip(),
            self.city and self.city.strip()
        ])
        
        documents_complete = all([
            self.document_front_url and self.document_front_url.strip(),
            self.document_back_url and self.document_back_url.strip(),
            self.selfie_url and self.selfie_url.strip()
        ])
        
        return names_complete and identity_complete and documents_complete
    
    @property
    def display_name(self) -> str:
        if self.first_name and self.last_name:
            full_name = f"{self.first_name} {self.last_name}"
            return full_name.strip()
        
        if self.telegram_first_name:
            full_name = self.telegram_first_name
            if self.telegram_last_name:
                full_name += f" {self.telegram_last_name}"
            return full_name
        
        return self.telegram_username or f"Usuario {self.telegram_id}"
    
    @property
    def full_legal_name(self) -> str:
        names = [
            self.first_name,
            self.middle_name,
            self.last_name,
            self.second_last_name
        ]
        return " ".join(n for n in names if n and n.strip())
    
    @property
    def full_phone(self) -> str:
        if self.country_code and self.phone:
            code = self.country_code if self.country_code.startswith("+") else f"+{self.country_code}"
            return f"{code}{self.phone}"
        return self.phone or ""

    def to_dict(self):
        return {
            "uuid": str(self.uuid),
            "telegram_id": self.telegram_id,
            "telegram_username": self.telegram_username,
            "status": self.status,
            "lang": self.lang,
            "balance": {
                "recharge": float(self.balance_recharge),
                "withdrawable": float(self.balance_withdrawable),
                "locked": float(self.balance_locked),
                "total": float(self.balance_total)
            },
            "is_profile_complete": self.is_profile_complete,
            "is_verified": self.is_verified,
            "email": self.email,
            "phone": self.full_phone,
            "country": self.country,
            "city": self.city,
            "full_name": self.display_name
        }

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, telegram_id={self.telegram_id}, "
            f"status={self.status}, verified={self.is_verified})>"
        )
