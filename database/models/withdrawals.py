# ============================================================
# database/models/withdrawals.py — PITIUPI V6.1 AML
# ✅ CORREGIDO: Sin dependencias circulares
# ============================================================

import uuid
from decimal import Decimal
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, Boolean,
    ForeignKey, DateTime, Index
)
from sqlalchemy.orm import relationship

from database.models.base import Base, TimestampMixin


class WithdrawalStatus:
    REQUESTED = "requested"
    PROCESSING = "processing"
    APPROVED = "approved"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class WithdrawalRequest(Base, TimestampMixin):
    """
    ✅ V6.1 AML: Solicitud de retiro sin dependencias circulares.
    """
    
    __tablename__ = "withdrawal_requests"

    # --------------------------------------------------------
    # Identificadores
    # --------------------------------------------------------
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False, index=True)

    # --------------------------------------------------------
    # Usuario solicitante
    # --------------------------------------------------------
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # ✅ Relación simple sin importar User directamente
    user = relationship("User", foreign_keys=[user_id])

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
    
    processed_by_user = relationship("User", foreign_keys=[processed_by])
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

    def calculate_net_amount(self, fee_percentage: Decimal = Decimal("0.00")):
        if fee_percentage > 0:
            self.fee = (self.amount * fee_percentage) / Decimal("100")
        else:
            self.fee = Decimal("0.00")
        
        self.net_amount = self.amount - self.fee

    def to_dict(self):
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
