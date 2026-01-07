# ============================================================
# database/models/withdrawals.py — PITIUPI V6.1 AML
# Modelo de solicitudes de retiro (Withdrawals)
# ✅ Compatible con SQLAlchemy 2.0 + PostgreSQL
# ============================================================

import uuid
from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, Boolean,
    ForeignKey, DateTime, Index
)
from sqlalchemy.orm import relationship

from database.models.base import Base, TimestampMixin
from database.types import UUIDType, JSONType
from database.models.user import User
from database.models.transactions import Transaction


# ============================================================
# Estados del retiro
# ============================================================

class WithdrawalStatus:
    """
    Estados posibles de una solicitud de retiro.
    
    Flow típico:
    REQUESTED → PROCESSING → APPROVED
    REQUESTED → DECLINED
    REQUESTED → CANCELLED (por usuario, antes de procesarse)
    """
    REQUESTED = "requested"      # Solicitado por usuario
    PROCESSING = "processing"    # En proceso por admin
    APPROVED = "approved"        # Aprobado y enviado
    DECLINED = "declined"        # Rechazado por admin
    CANCELLED = "cancelled"      # Cancelado por usuario


# ============================================================
# Modelo WithdrawalRequest
# ============================================================

class WithdrawalRequest(Base, TimestampMixin):
    """
    ✅ V6.1 AML: Solicitud de retiro de balance_withdrawable.
    
    Relaciones Corregidas:
    - user: El usuario que retira (back_populates="withdrawal_requests")
    - processed_by_user: El admin que aprueba/rechaza (sin backref conflictivo)
    """
    
    __tablename__ = "withdrawal_requests"

    # --------------------------------------------------------
    # Identificadores
    # --------------------------------------------------------
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(UUIDType, default=uuid.uuid4, unique=True, nullable=False, index=True)

    # --------------------------------------------------------
    # Usuario solicitante
    # --------------------------------------------------------
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # ✅ Relación Principal: Conectada con User.withdrawal_requests
    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="withdrawal_requests"
    )

    # --------------------------------------------------------
    # Información financiera
    # --------------------------------------------------------
    amount = Column(Numeric(18, 2), nullable=False)
    fee = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    net_amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)

    # --------------------------------------------------------
    # Método de pago
    # --------------------------------------------------------
    method = Column(String(32), nullable=False, index=True)
    details = Column(Text, nullable=False)

    # --------------------------------------------------------
    # Estado y procesamiento
    # --------------------------------------------------------
    status = Column(
        String(32),
        default=WithdrawalStatus.REQUESTED,
        nullable=False,
        index=True
    )
    status_reason = Column(Text, nullable=True)

    # --------------------------------------------------------
    # Admin que procesa
    # --------------------------------------------------------
    processed_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # ✅ Relación Administrativa: Usamos overlaps para evitar errores de Mapper
    processed_by_user = relationship(
        "User",
        foreign_keys=[processed_by],
        overlaps="user" 
    )

    processed_at = Column(DateTime(timezone=True), nullable=True)

    # --------------------------------------------------------
    # ID externo de la transacción
    # --------------------------------------------------------
    transaction_id = Column(String(128), nullable=True, index=True)

    # --------------------------------------------------------
    # Auditoría adicional
    # --------------------------------------------------------
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # --------------------------------------------------------
    # Índices optimizados
    # --------------------------------------------------------
    __table_args__ = (
        Index("idx_withdrawals_user_status", "user_id", "status"),
        Index("idx_withdrawals_status_created", "status", "created_at"),
        Index("idx_withdrawals_processed_at", "processed_at"),
        Index("idx_withdrawals_method", "method"),
        Index("idx_withdrawals_uuid", "uuid", unique=True),
    )

    def to_dict(self):
        """Serializa información importante del retiro."""
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "user_id": self.user_id,
            "amount": float(self.amount),
            "fee": float(self.fee),
            "net_amount": float(self.net_amount),
            "currency": self.currency,
            "status": self.status,
            "method": self.method,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "status_reason": self.status_reason
        }

    # --------------------------------------------------------
    # Métodos auxiliares
    # --------------------------------------------------------
    
    def calculate_net_amount(self, fee_percentage: Decimal = Decimal("0.00")):
        """
        Calcula el monto neto después de aplicar comisión.
        
        Args:
            fee_percentage: Porcentaje de comisión (ej: 2.5 para 2.5%)
        
        Example:
            withdrawal.calculate_net_amount(Decimal("2.5"))
            # amount=100 → fee=2.50 → net_amount=97.50
        """
        if fee_percentage > 0:
            self.fee = (self.amount * fee_percentage) / Decimal("100")
        else:
            self.fee = Decimal("0.00")
        
        self.net_amount = self.amount - self.fee

    def to_dict(self):
        """
        Serialización para API interna o respuestas JSON.
        
        Returns:
            dict con información del retiro
        """
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "user_id": self.user_id,
            "amount": float(self.amount),
            "fee": float(self.fee),
            "net_amount": float(self.net_amount),
            "currency": self.currency,
            "method": self.method,
            "status": self.status,
            "status_reason": self.status_reason,
            "processed_by": self.processed_by,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<WithdrawalRequest(id={self.id}, "
            f"user_id={self.user_id}, "
            f"amount=${self.amount}, "
            f"method={self.method}, "
            f"status={self.status})>"
        )
