import uuid
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database.models.base import Base, TimestampMixin

class PayoutIntent(Base, TimestampMixin):
    __tablename__ = "payout_intents"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    user = relationship("User")

    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")
    
    # Runa specific
    runa_order_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), default="pending", index=True) # pending, processing, completed, failed
    
    # Masked recipient info
    recipient_email = Column(String(255), nullable=True)
    card_last4 = Column(String(4), nullable=True)

    raw_response = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_payouts_status", "status"),
    )
