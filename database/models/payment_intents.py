# ============================================================
# database/models/payment_intent.py
# Modelo de intenciones de pago - PITIUPI V6
# Alineado con arquitectura V6 y flujo Nuvei LinkToPay
# ============================================================

import uuid
from datetime import datetime, timedelta
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, DateTime,
    Text, ForeignKey, Enum, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declared_attr

from database.models.base import Base


# ============================================================
# MIXIN PARA TIMESTAMPS
# ============================================================
class TimestampMixin:
    """Mixin para agregar timestamps automáticos"""
    
    @declared_attr
    def created_at(cls):
        return Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    @declared_attr
    def updated_at(cls):
        return Column(
            DateTime(timezone=True),
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
            nullable=False
        )


# ============================================================
# ESTADOS V6 SIMPLIFICADOS
# ============================================================
class PaymentIntentStatus(PyEnum):
    """Estados simplificados V6 - Solo reflejan proceso externo"""
    PENDING = "pending"        # Creado, esperando pago
    COMPLETED = "completed"    # Confirmado por webhook Nuvei
    FAILED = "failed"         # Declinado / error
    EXPIRED = "expired"       # Expirado (no usado en webhook)


# ============================================================
# MODELO PAYMENT INTENT V6
# ============================================================
class PaymentIntent(Base, TimestampMixin):
    """
    Payment Intent V6 - Intención de pago con proveedor externo
    
    PRINCIPIOS V6:
    1. Representa proceso externo (Nuvei), NO dinero real
    2. Ciclo de vida simplificado (PENDING → COMPLETED/FAILED)
    3. provider_intent_id nullable (se asigna después de crear)
    4. COMPLETED solo cuando el ledger registra Transaction
    """
    
    __tablename__ = "payment_intents"
    
    # IDENTIFICACIÓN
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
    # USUARIO (relación bidireccional)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    user = relationship("User", back_populates="payment_intents")
    
    # PROVEEDOR (Nuvei)
    provider = Column(String(32), default="nuvei", nullable=False)
    
    # IDs DEL PROVEEDOR (nullable porque se asignan después)
    provider_intent_id = Column(String(128), nullable=True, index=True)  # ✅ Nullable V6
    provider_order_id = Column(String(128), nullable=True, index=True)   # order_id LinkToPay
    
    # DATOS FINANCIEROS
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    amount_received = Column(Numeric(18, 2), nullable=True)  # Actualizado por webhook
    
    # ESTADO V6 (simplificado)
    status = Column(
        Enum(PaymentIntentStatus, name="payment_intent_status"),
        default=PaymentIntentStatus.PENDING,
        nullable=False,
        index=True
    )
    
    # RAZÓN DE FALLO (para FAILED/EXPIRED)
    failure_reason = Column(Text, nullable=True)
    
    # REFERENCIA AL LEDGER (cuando se completa)
    ledger_transaction_uuid = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    # METADATA Y WEBHOOK
    details = Column(JSONB, default=dict, nullable=False)  # Datos específicos del proveedor
    webhook_payload = Column(JSONB, nullable=True)  # Payload original del webhook Nuvei
    
    # TIEMPOS DE ESTADO
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Vencimiento automático
    completed_at = Column(DateTime(timezone=True), nullable=True)  # Solo cuando hay Transaction
    failed_at = Column(DateTime(timezone=True), nullable=True)  # Para FAILED/EXPIRED
    
    # ÍNDICES OPTIMIZADOS V6
    __table_args__ = (
        Index("idx_payment_intents_user_status", "user_id", "status"),
        Index("idx_payment_intents_provider_ids", "provider", "provider_intent_id"),
        Index("idx_payment_intents_uuid", "uuid", unique=True),
        Index("idx_payment_intents_expires", "expires_at"),
        Index("idx_payment_intents_created", "created_at"),
    )
    
    # ============================================================
    # PROPIEDADES COMPUTADAS (V6)
    # ============================================================
    
    @property
    def is_completed(self) -> bool:
        """Indica si el intent está completado y tiene ledger"""
        return self.status == PaymentIntentStatus.COMPLETED and self.ledger_transaction_uuid is not None
    
    @property
    def is_pending(self) -> bool:
        """Indica si está esperando pago"""
        return self.status == PaymentIntentStatus.PENDING
    
    @property
    def is_failed(self) -> bool:
        """Indica si falló o expiró"""
        return self.status in (PaymentIntentStatus.FAILED, PaymentIntentStatus.EXPIRED)
    
    @property
    def is_expired(self) -> bool:
        """Indica si expiró (subset de is_failed)"""
        return self.status == PaymentIntentStatus.EXPIRED
    
    @property
    def effective_amount(self) -> float:
        """Devuelve el monto efectivo (recibido o solicitado)"""
        return float(self.amount_received) if self.amount_received else float(self.amount)
    
    @property
    def is_expired_now(self) -> bool:
        """Verifica si el intent ha expirado"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    # ============================================================
    # MÉTODOS DE SERIALIZACIÓN
    # ============================================================
    
    def to_dict(self) -> dict:
        """Serializa el intent para respuestas del backend/handlers"""
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "user_id": self.user_id,
            "provider": self.provider,
            "provider_intent_id": self.provider_intent_id,
            "provider_order_id": self.provider_order_id,
            "amount": float(self.amount),
            "amount_received": float(self.amount_received) if self.amount_received else None,
            "currency": self.currency,
            "status": self.status.value,
            "failure_reason": self.failure_reason,
            "ledger_transaction_uuid": str(self.ledger_transaction_uuid) if self.ledger_transaction_uuid else None,
            "details": self.details,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def to_webhook_dict(self) -> dict:
        """Serialización específica para webhooks Nuvei"""
        return {
            "uuid": str(self.uuid),
            "user_id": self.user_id,
            "amount": float(self.amount),
            "amount_received": float(self.amount_received) if self.amount_received else float(self.amount),
            "currency": self.currency,
            "provider_intent_id": self.provider_intent_id,
            "provider_order_id": self.provider_order_id,
            "status": self.status.value,
            "details": self.details,
        }
    
    def __repr__(self) -> str:
        return (
            f"<PaymentIntent(id={self.id}, uuid={self.uuid}, "
            f"user_id={self.user_id}, amount={self.amount}, "
            f"status={self.status.value}, provider_intent_id={self.provider_intent_id})>"
        )
