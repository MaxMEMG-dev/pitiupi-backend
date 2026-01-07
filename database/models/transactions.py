# ============================================================
# database/models/transactions.py
# Modelo de Ledger - PITIUPI V6
# SINGLE SOURCE OF TRUTH: PostgreSQL
# Append-only - Nunca se modifica - Auditoría completa
# ============================================================

import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

# ✅ IMPORTACIÓN DIRECTA (evita ciclos)
from database.models.base import Base, TimestampMixin


# ============================================================
# CONSTANTES DE TIPO DE TRANSACCIÓN (V6)
# ============================================================
class TransactionType:
    """Tipos de transacción - LÓGICA DE NEGOCIO PURA"""
    # Transacciones que afectan balance
    DEPOSIT = "deposit"
    DEDUCTION = "deduction"  # ✅ Agregado para users_service
    WITHDRAWAL = "withdrawal"
    
    # Retos y competencias
    BET = "bet"
    BET_WIN = "bet_win"
    BET_LOSS = "bet_loss"
    CHALLENGE_WIN = "challenge_win"  # ✅ Alias de BET_WIN
    CHALLENGE_LOSS = "challenge_loss"  # ✅ Alias de BET_LOSS
    
    # Torneos y premios
    TOURNAMENT_PRIZE = "tournament_prize"
    BONUS = "bonus"
    ADJUSTMENT = "adjustment"
    FEE = "fee"
    
    # Operaciones internas (NO afectan balance_total)
    BALANCE_FREEZE = "balance_freeze"
    BALANCE_UNFREEZE = "balance_unfreeze"
    BALANCE_CONSUMED = "balance_consumed"
    
    # Estados de retiro (proceso administrativo)
    WITHDRAWAL_REQUEST = "withdrawal_request"
    WITHDRAWAL_APPROVED = "withdrawal_approved"
    WITHDRAWAL_REJECTED = "withdrawal_rejected"
    WITHDRAWAL_CANCELLED = "withdrawal_cancelled"
    
    # Eventos de sistema (NO afectan balance)
    USER_CREATED = "user_created"
    PROFILE_UPDATED = "profile_updated"
    PAYMENT_INTENT_CREATED = "payment_intent_created"
    PAYMENT_CONFIRMED = "payment_confirmed"
    LEDGER_CORRECTION = "ledger_correction"


# ============================================================
# MODELO TRANSACTION (LEDGER) - V6 FINAL
# ✅ RENOMBRADO A: Transaction
# ============================================================
class Transaction(Base):
    """
    LEDGER V6 - REGISTRO CONTABLE INMUTABLE
    
    ✅ NOMBRE CAMBIADO: Transaction (evita colisión con SQLAlchemy)
    
    PRINCIPIOS V6:
    1. Append-only (nunca se modifica)
    2. Sin status (es histórico, ya está completado)
    3. Sin updated_at (inmutable)
    4. Sin is_reversed (compensar con nueva transacción)
    5. Auditoría completa (balance_before + balance_after)
    6. Single Source of Truth para estado financiero
    """
    
    __tablename__ = "transactions"
    
    # IDENTIFICACIÓN
    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
    # USUARIO (relación)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    user = relationship("User", back_populates="transactions")
    
    # TIPO Y MONTO (core)
    type = Column(String(64), nullable=False, index=True)  # Usa TransactionType
    amount = Column(Numeric(18, 2), nullable=False)  # Monto de la transacción
    currency = Column(String(3), default="USD", nullable=False)
    
    # BALANCE (auditoría completa) - ✅ OPCIONALES para permitir transacciones sin snapshot
    balance_before = Column(Numeric(18, 2), nullable=True)
    balance_after = Column(Numeric(18, 2), nullable=True)
    
    # REFERENCIAS (trazabilidad)
    reference_type = Column(String(64), index=True)  # Ej: "payment_intent", "withdrawal_request"
    reference_id = Column(String(128), index=True)   # Ej: UUID del payment_intent
    
    # METADATA
    description = Column(Text, nullable=False)
    details = Column(JSONB, default=dict, nullable=False)
    
    # TIMESTAMP (solo created_at - inmutable)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    # ÍNDICES (optimización para consultas comunes)
    __table_args__ = (
        Index("idx_transactions_user_created", "user_id", "created_at"),
        Index("idx_transactions_reference", "reference_type", "reference_id"),
        Index("idx_transactions_type_created", "type", "created_at"),
        Index("idx_transactions_uuid", "uuid", unique=True),
        Index("idx_transactions_created", "created_at"),
    )
    
    def to_dict(self) -> dict:
        """Representación serializable para auditoría"""
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "user_id": self.user_id,
            "type": self.type,
            "amount": float(self.amount) if self.amount else 0.0,
            "currency": self.currency,
            "balance_before": float(self.balance_before) if self.balance_before else None,
            "balance_after": float(self.balance_after) if self.balance_after else None,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "description": self.description,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return (
            f"<Transaction(id={self.id}, user_id={self.user_id}, "
            f"type={self.type}, amount={self.amount})>"
        )


# ============================================================
# EXPORTACIONES
# ============================================================
__all__ = [
    "Transaction",
    "TransactionType",
]
