import uuid
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database.models.base import Base, TimestampMixin

class PayoutIntent(Base, TimestampMixin):
    __tablename__ = "payout_intents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # UUID para Idempotencia (external_id en Runa)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="payout_intents")

    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    
    # Runa Response Data
    runa_order_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), default="pending", index=True) # pending, completed, failed
    
    # Datos del beneficiario (guardar solo lo necesario)
    recipient_email = Column(String(255), nullable=True)
    
    # Respuesta completa para depuración
    raw_response = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_payouts_uuid", "uuid"),
    )
