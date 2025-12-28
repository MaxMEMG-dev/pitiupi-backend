# ============================================================
# database/models/user.py
# Modelo principal de usuario PITIUPI v6.1 AML
# ✅ ACTUALIZADO: Separación balance_recharge / balance_withdrawable
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
    
    ✅ V6.1 AML: Separación de balances para cumplimiento regulatorio
    - balance_recharge: Dinero depositado (NO retirable hasta ganar)
    - balance_withdrawable: Dinero ganado en retos (SÍ retirable)
    - balance_available: Propiedad calculada (recharge + withdrawable)
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
    # Balance V6.1 AML (Mantenido por users_service mediante FOR UPDATE)
    # --------------------------------------------------------
    # ✅ NUEVO: Separación de saldos para cumplimiento AML
    balance_recharge = Column(
        Numeric(18, 2), 
        default=Decimal("0.00"), 
        nullable=False,
        comment="Depósitos directos - NO retirable hasta ganar retos"
    )
    
    balance_withdrawable = Column(
        Numeric(18, 2), 
        default=Decimal("0.00"), 
        nullable=False,
        comment="Ganancias de retos - SÍ retirable"
    )
    
    balance_locked = Column(
        Numeric(18, 2), 
        default=Decimal("0.00"), 
        nullable=False,
        comment="Dinero bloqueado en retos activos o retiros pendientes"
    )
    
    balance_total = Column(
        Numeric(18, 2), 
        default=Decimal("0.00"), 
        nullable=False,
        comment="Suma total: recharge + withdrawable + locked"
    )

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
    # Relaciones (Ajustadas para V6.1 - Lazy Loading)
    # --------------------------------------------------------
    # ✅ CORREGIDO: Usar string reference + lazy='dynamic' para evitar circular imports
    transactions = relationship(
        "Transaction",
        back_populates="user",
        cascade="save-update, merge",
        lazy="dynamic",
        order_by="Transaction.created_at.desc()"
    )
    
    # ✅ Relación con PaymentIntents
    payment_intents = relationship(
        "PaymentIntent",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="PaymentIntent.created_at.desc()"
    )
    
    # ✅ Relación con WithdrawalRequests
    withdrawal_requests = relationship(
        "WithdrawalRequest",
        foreign_keys="WithdrawalRequest.user_id",
        back_populates="user",
        lazy="dynamic",
        order_by="WithdrawalRequest.created_at.desc()"
    )
    
    # Relaciones de retos
    challenges_as_challenger = relationship(
        "Challenge",
        foreign_keys="Challenge.challenger_id",
        back_populates="challenger",
        lazy="dynamic"
    )

    challenges_as_opponent = relationship(
        "Challenge",
        foreign_keys="Challenge.opponent_id",
        back_populates="opponent",
        lazy="dynamic"
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
        Index("idx_users_status_lang", "status", "lang"),
        Index("idx_users_balance_withdrawable", "balance_withdrawable"),  # ✅ Nuevo
        Index("idx_users_balance_recharge", "balance_recharge"),  # ✅ Nuevo
    )

    # --------------------------------------------------------
    # Propiedades Calculadas V6.1 AML
    # --------------------------------------------------------
    
    @property
    def balance_available(self) -> Decimal:
        """
        ✅ V6.1 AML: Balance disponible para jugar.
        
        Este es el dinero que el usuario puede usar para crear/aceptar retos.
        Suma de:
        - balance_recharge (depósitos)
        - balance_withdrawable (ganancias)
        
        NO incluye balance_locked (está en uso).
        
        Returns:
            Decimal: Total disponible para apostar
        """
        return self.balance_recharge + self.balance_withdrawable

    @property
    def is_profile_complete(self) -> bool:
        """
        Lógica central de Onboarding V6.
        Define si el usuario puede operar/pagar.
        
        Returns:
            bool: True si todos los campos requeridos están completos
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
        """
        Nombre para mostrar en UI.
        
        Returns:
            str: Nombre completo, username o ID
        """
        if self.telegram_first_name:
            full_name = self.telegram_first_name
            if self.telegram_last_name:
                full_name += f" {self.telegram_last_name}"
            return full_name
        return self.telegram_username or f"Usuario {self.telegram_id}"

    # --------------------------------------------------------
    # Validaciones V6.1 AML
    # --------------------------------------------------------
    
    @validates("balance_recharge", "balance_withdrawable", "balance_locked")
    def validate_balance(self, key, value):
        """
        ✅ V6.1: Validar que ningún balance sea negativo.
        
        Args:
            key: Nombre del campo
            value: Valor a validar
            
        Returns:
            Decimal: Valor validado
            
        Raises:
            ValueError: Si el balance es negativo
        """
        if value is not None and Decimal(str(value)) < Decimal("0.00"):
            raise ValueError(f"{key} no puede ser negativo. Valor recibido: {value}")
        return value

    @validates("lang")
    def validate_lang(self, key, value):
        """
        Valida que el idioma sea válido.
        
        Args:
            key: Nombre del campo
            value: Valor a validar
            
        Returns:
            str: Idioma validado
            
        Raises:
            ValueError: Si el idioma no es 'es' o 'en'
        """
        if value not in ["es", "en"]:
            raise ValueError(f"Idioma debe ser 'es' o 'en'. Valor recibido: {value}")
        return value

    # --------------------------------------------------------
    # Métodos Auxiliares V6.1 AML
    # --------------------------------------------------------
    
    def recalculate_total(self):
        """
        ✅ V6.1 AML: Recalcula balance_total.
        
        IMPORTANTE: Llamar este método antes de commit() cuando se modifiquen
        balance_recharge, balance_withdrawable o balance_locked.
        
        Formula:
            balance_total = balance_recharge + balance_withdrawable + balance_locked
        
        Example:
            user.balance_recharge += 10
            user.recalculate_total()
            session.commit()
        """
        self.balance_total = (
            self.balance_recharge + 
            self.balance_withdrawable + 
            self.balance_locked
        )

    def to_dict(self):
        """
        ✅ V6.1 AML: Serialización para API interna con balances separados.
        
        Returns:
            dict: Representación del usuario con todos sus balances
        """
        return {
            "uuid": str(self.uuid),
            "telegram_id": self.telegram_id,
            "telegram_username": self.telegram_username,
            "telegram_first_name": self.telegram_first_name,
            "telegram_last_name": self.telegram_last_name,
            "display_name": self.display_name,
            "status": self.status,
            "lang": self.lang,
            "balance": {
                "recharge": float(self.balance_recharge),        # ✅ NO retirable
                "withdrawable": float(self.balance_withdrawable), # ✅ SÍ retirable
                "available": float(self.balance_available),      # ✅ Calculado
                "locked": float(self.balance_locked),
                "total": float(self.balance_total)
            },
            "profile": {
                "is_complete": self.is_profile_complete,
                "email": self.email,
                "phone": self.phone,
                "country": self.country,
                "city": self.city,
                "document_number": self.document_number,
                "birthdate": self.birthdate
            },
            "onboarding": {
                "terms_accepted": self.terms_accepted,
                "terms_accepted_at": self.terms_accepted_at.isoformat() if self.terms_accepted_at else None,
                "first_deposit_completed": self.first_deposit_completed,
                "first_deposit_at": self.first_deposit_at.isoformat() if self.first_deposit_at else None
            },
            "stats": {
                "total_deposits": float(self.total_deposits),
                "total_wins": float(self.total_wins),
                "kyc_status": self.kyc_status
            },
            "timestamps": {
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "last_active_at": self.last_active_at.isoformat() if self.last_active_at else None
            }
        }

    def __repr__(self) -> str:
        """
        Representación string del usuario para debugging.
        
        Returns:
            str: Representación del objeto User
        """
        return (
            f"<User(id={self.id}, "
            f"telegram_id={self.telegram_id}, "
            f"status={self.status}, "
            f"lang={self.lang}, "
            f"balance_available={self.balance_available}, "
            f"balance_withdrawable={self.balance_withdrawable})>"
        )
