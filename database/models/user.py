# ============================================================
# database/models/user.py
# Modelo principal de usuario PITIUPI v6.2
# ✅ ACTUALIZADO: Sistema KYC con verificación manual
# ✅ AGREGADO: Campos de identidad completos (4 nombres)
# ✅ AGREGADO: URLs de documentos (front, back, selfie)
# ✅ CORREGIDO: Estados de aprobación y verificación
# ✅ NUEVO: Campos para flujo de onboarding completo y primer depósito
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
    """Estados del usuario en el sistema"""
    PENDING = "pending_approval"
    PENDING_APPROVAL = "pending_approval"  # ✅ Esperando verificación KYC
    ACTIVE = "active"                      # ✅ Verificado y operativo
    REJECTED = "rejected"                  # ✅ KYC rechazado
    BANNED = "banned"                      # ✅ Bloqueado por admin
    SUSPENDED = "suspended"                # Suspendido temporalmente


class User(Base, TimestampMixin):
    """
    Modelo principal de usuario con KYC manual.
    Single Source of Truth para la identidad y el estado financiero actual.
    """
    __tablename__ = "users"

    # --------------------------------------------------------
    # Identidad Básica y Telegram
    # --------------------------------------------------------
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(UUIDType, default=uuid.uuid4, unique=True, nullable=False)
    
    telegram_id = Column(String(64), unique=True, nullable=False, index=True)
    telegram_username = Column(String(64), index=True, nullable=True)
    telegram_first_name = Column(String(128), nullable=True)  # Mantenido para respaldo
    telegram_last_name = Column(String(128), nullable=True)   # Mantenido para respaldo

    # --------------------------------------------------------
    # ✅ NUEVOS: Datos de Identidad Completos (KYC)
    # --------------------------------------------------------
    first_name = Column(String(128), nullable=True)        # Primer nombre (REQUERIDO)
    middle_name = Column(String(128), nullable=True)       # Segundo nombre (OPCIONAL)
    last_name = Column(String(128), nullable=True)         # Primer apellido (REQUERIDO)
    second_last_name = Column(String(128), nullable=True)  # Segundo apellido (OPCIONAL)
    
    document_number = Column(String(64), nullable=True)    # Número de documento
    birthdate = Column(String(32), nullable=True)          # Formato "YYYY-MM-DD"
    email = Column(String(255), nullable=True, unique=True)
    
    # ✅ ACTUALIZADO: Teléfono separado en código de país y número
    country_code = Column(String(10), nullable=True)       # Código de país (ej: "+593")
    phone = Column(String(32), nullable=True)              # Número sin código de país
    
    country = Column(String(64), nullable=True)
    city = Column(String(128), nullable=True)

    # --------------------------------------------------------
    # ✅ NUEVOS: URLs de Documentos KYC (Text para URLs largas)
    # --------------------------------------------------------
    document_front_url = Column(Text, nullable=True)  # Foto frontal del documento (URLs firmadas pueden ser largas)
    document_back_url = Column(Text, nullable=True)   # Foto trasera del documento
    selfie_url = Column(Text, nullable=True)          # Selfie con documento
    
    # Razon del rechazo
    rejection_reason = Column(String(500), nullable=True)

    # --------------------------------------------------------
    # ✅ ACTUALIZADO: Estado y Verificación
    # --------------------------------------------------------
    status = Column(
        String(32), 
        default=UserStatus.PENDING_APPROVAL,  # ✅ Por defecto pendiente de aprobación
        nullable=False
    )
    is_admin = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)  # ✅ Se activa al aprobar KYC
    lang = Column(String(2), default="es", nullable=False)  # 'es' o 'en'

    # --------------------------------------------------------
    # Balance (Mantenido por users_service mediante FOR UPDATE)
    # --------------------------------------------------------
    
    # balance_recharge: Dinero depositado (debe jugarse para ser retirable)
    balance_recharge = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    # balance_withdrawable: Dinero retirable (ganancias de retos)
    balance_withdrawable = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    balance_locked = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    # El total ahora es la suma de los tres
    balance_total = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)

    # --------------------------------------------------------
    # Datos de Registro / Onboarding
    # --------------------------------------------------------
    # ✅ CORREGIDO: Uso de server_default para evitar errores de tipo SQL
    terms_accepted = Column(Boolean, nullable=False, server_default="false")
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    
    registration_completed = Column(Boolean, nullable=False, server_default="false")
    first_deposit_made = Column(Boolean, nullable=False, server_default="false")
    first_deposit_amount = Column(Numeric(10, 2), nullable=True)
    first_deposit_date = Column(DateTime, nullable=True)
    
    # --------------------------------------------------------
    # KYC y Métricas
    # --------------------------------------------------------
    kyc_status = Column(String(32), nullable=True, server_default="pending")  # Estado interno adicional si se necesita
    kyc_submitted_at = Column(DateTime, nullable=True)  # Cuando envió KYC
    kyc_approved_at = Column(DateTime, nullable=True)   # Cuando fue aprobado
    kyc_rejected_at = Column(DateTime, nullable=True)   # Cuando fue rechazado
    
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
    
#    # ✅ Relación con WithdrawalRequests (V6.1 AML)
#    withdrawal_requests = relationship(
#        "WithdrawalRequest",
#        foreign_keys="[WithdrawalRequest.user_id]", 
#        back_populates="user",
#        cascade="save-update, merge",
#        lazy="dynamic",
#        order_by="WithdrawalRequest.created_at.desc()"
#    )
    
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
        Index("idx_users_is_verified", "is_verified"),  # ✅ Nuevo índice
    )

    # --------------------------------------------------------
    # Validaciones y Helpers
    # --------------------------------------------------------
    @validates("balance_recharge", "balance_withdrawable", "balance_locked")
    def validate_balance(self, key, value):
        if value is not None and Decimal(str(value)) < Decimal("0.00"):
            raise ValueError(f"{key} no puede ser negativo")
        return value

    @validates("lang")
    def validate_lang(self, key, value):
        """
        ✅ ACTUALIZADO V6.2: Permite None para usuarios nuevos sin idioma
        """
        # ✅ Permitir None para que el bot pida selección de idioma
        if value is None:
            return None
        
        # Solo validar si se proporciona un idioma
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
        """Helper para actualizar balance_total antes de commit."""
        self.balance_total = self.balance_recharge + self.balance_withdrawable + self.balance_locked

    @property
    def balance_available(self):
        """Propiedad calculada para compatibilidad con código existente."""
        return self.balance_recharge + self.balance_withdrawable

    def to_dict(self):
        """Serialización para API interna."""
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
            "phone": self.full_phone,  # ✅ Teléfono completo con código
            "country": self.country,
            "city": self.city,
            "full_name": self.display_name
        }

    # --------------------------------------------------------
    # ✅ ACTUALIZADO: Propiedades KYC
    # --------------------------------------------------------
    
    @property
    def can_access_menu(self) -> bool:
        """Verifica si el usuario puede acceder al menú principal"""
        return (
            self.status == UserStatus.ACTIVE and 
            self.is_verified and 
            self.registration_completed and
            self.first_deposit_made
        )

    @property
    def is_profile_complete(self) -> bool:
        """
        ✅ ACTUALIZADO: Lógica KYC completa con campos opcionales.
        Define si el usuario ha completado todo el proceso de registro.
        
        CAMPOS OBLIGATORIOS:
        - first_name y last_name (nombres básicos)
        - document_number, birthdate
        - email, country_code, phone
        - country, city
        - Las 3 fotos (documento front/back y selfie)
        
        CAMPOS OPCIONALES:
        - middle_name y second_last_name (no todos tienen segundo nombre/apellido)
        """
        # Validar nombres (mínimo primer nombre y primer apellido)
        names_complete = all([
            self.first_name and self.first_name.strip(),
            self.last_name and self.last_name.strip()
        ])
        
        # Validar datos de contacto e identidad
        identity_complete = all([
            self.document_number and self.document_number.strip(),
            self.birthdate and self.birthdate.strip(),
            self.email and self.email.strip(),
            self.country_code and self.country_code.strip(),  # ✅ Código de país
            self.phone and self.phone.strip(),
            self.country and self.country.strip(),
            self.city and self.city.strip()
        ])
        
        # Validar documentos KYC (las 3 fotos)
        documents_complete = all([
            self.document_front_url and self.document_front_url.strip(),
            self.document_back_url and self.document_back_url.strip(),
            self.selfie_url and self.selfie_url.strip()
        ])
        
        return names_complete and identity_complete and documents_complete
    
    @property
    def display_name(self) -> str:
        """
        ✅ ACTUALIZADO: Nombre completo para mostrar en UI.
        
        Prioridad:
        1. first_name + last_name (datos KYC)
        2. telegram_first_name + telegram_last_name (respaldo)
        3. telegram_username
        4. ID de Telegram
        """
        # Intentar usar datos KYC primero
        if self.first_name and self.last_name:
            full_name = f"{self.first_name} {self.last_name}"
            return full_name.strip()
        
        # Respaldo: usar datos de Telegram
        if self.telegram_first_name:
            full_name = self.telegram_first_name
            if self.telegram_last_name:
                full_name += f" {self.telegram_last_name}"
            return full_name
        
        # Último respaldo: username o ID
        return self.telegram_username or f"Usuario {self.telegram_id}"
    
    @property
    def full_legal_name(self) -> str:
        """
        ✅ ACTUALIZADO: Nombre legal completo (incluye nombres opcionales si existen).
        Usado para documentos oficiales y verificación.
        """
        names = [
            self.first_name,
            self.middle_name,      # Opcional
            self.last_name,
            self.second_last_name  # Opcional
        ]
        return " ".join(n for n in names if n and n.strip())
    
    @property
    def full_phone(self) -> str:
        """
        ✅ NUEVO: Teléfono completo con código de país.
        Retorna el número en formato internacional.
        Ejemplo: "+593987654321"
        """
        if self.country_code and self.phone:
            # Asegurar que el código tenga el "+"
            code = self.country_code if self.country_code.startswith("+") else f"+{self.country_code}"
            return f"{code}{self.phone}"
        return self.phone or ""

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, telegram_id={self.telegram_id}, "
            f"status={self.status}, verified={self.is_verified})>"
        )
