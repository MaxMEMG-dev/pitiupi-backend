# ============================================================
# database/models/challenges.py
# Modelo de retos (Challenge) - VERSIÓN CORREGIDA V6
# ✅ CORREGIDO: Sin back_populates conflictivos
# ✅ COMPATIBLE: Con User sin relaciones challenge
# ============================================================

import uuid
from sqlalchemy import (
    Column, Integer, String, Numeric, Text,
    ForeignKey, DateTime, Index
)
from sqlalchemy.orm import relationship

from database.models.base import Base, TimestampMixin


# ============================================================
# Estados del reto
# ============================================================

class ChallengeStatus:
    DRAFT = "draft"
    OPEN = "open"
    MATCHED = "matched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# ============================================================
# Modelo Challenge - VERSIÓN CORREGIDA
# ============================================================

class Challenge(Base, TimestampMixin):
    """
    Modelo de reto entre dos usuarios - VERSIÓN V6 CORREGIDA
    
    ✅ CORRECCIONES APLICADAS:
    1. Eliminado back_populates conflictivo
    2. Usa String para UUID (compatible con Neon)
    3. Relaciones simples sin referencias circulares
    4. Sin dependencia de database.types.UUIDType
    """

    __tablename__ = "challenges"

    # --------------------------------------------------------
    # Identificación
    # --------------------------------------------------------
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False)

    # --------------------------------------------------------
    # Participantes - RELACIONES SIMPLIFICADAS
    # --------------------------------------------------------
    challenger_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )
    opponent_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True
    )

    # ✅ RELACIONES SIMPLES SIN back_populates
    challenger = relationship(
        "User",
        foreign_keys=[challenger_id]
        # ⚠️ NO USAR: back_populates="challenges_as_challenger"
    )
    opponent = relationship(
        "User",
        foreign_keys=[opponent_id]
        # ⚠️ NO USAR: back_populates="challenges_as_opponent"
    )

    # --------------------------------------------------------
    # Finanzas del reto
    # --------------------------------------------------------
    bet_amount = Column(Numeric(18, 2), nullable=False)
    rake_percentage = Column(Numeric(5, 4), nullable=False)
    total_pot = Column(Numeric(18, 2), nullable=False)
    prize_amount = Column(Numeric(18, 2), nullable=False)

    # --------------------------------------------------------
    # Configuración del juego
    # --------------------------------------------------------
    game_name = Column(String(64), nullable=False, index=True)
    game_mode = Column(String(32), default="1v1", nullable=False)
    game_rules = Column(Text, nullable=True)
    game_link = Column(String(512), nullable=True)

    # --------------------------------------------------------
    # Estado y progreso
    # --------------------------------------------------------
    status = Column(
        String(32),
        default=ChallengeStatus.OPEN,
        nullable=False,
        index=True
    )

    # --------------------------------------------------------
    # Resultado
    # --------------------------------------------------------
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner = relationship("User", foreign_keys=[winner_id])

    # --------------------------------------------------------
    # Integración Telegram
    # --------------------------------------------------------
    telegram_chat_id = Column(String(64), nullable=True)
    telegram_message_id = Column(Integer, nullable=True)

    # --------------------------------------------------------
    # Tiempos y fechas
    # --------------------------------------------------------
    expires_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # --------------------------------------------------------
    # Auditoría
    # --------------------------------------------------------
    created_by_ip = Column(String(45), nullable=True)
    last_updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # --------------------------------------------------------
    # Índices optimizados
    # --------------------------------------------------------
    __table_args__ = (
        Index("idx_challenges_game", "game_name"),
        Index("idx_challenges_status_expires", "status", "expires_at"),
        Index("idx_challenges_challenger", "challenger_id", "status"),
        Index("idx_challenges_opponent", "opponent_id", "status"),
        Index("idx_challenges_created", "created_at"),
        Index("idx_challenges_uuid", "uuid", unique=True),
    )

    # --------------------------------------------------------
    # Métodos y propiedades
    # --------------------------------------------------------
    
    @property
    def is_open(self) -> bool:
        """Retorna True si el reto está abierto para unirse"""
        return self.status == ChallengeStatus.OPEN
    
    @property
    def is_active(self) -> bool:
        """Retorna True si el reto está en progreso"""
        return self.status == ChallengeStatus.IN_PROGRESS
    
    @property
    def is_completed(self) -> bool:
        """Retorna True si el reto está completado"""
        return self.status == ChallengeStatus.COMPLETED
    
    @property
    def rake_amount(self) -> float:
        """Calcula el monto de la comisión (rake)"""
        return float(self.bet_amount * self.rake_percentage)
    
    @property
    def net_prize(self) -> float:
        """Calcula el premio neto (después de comisión)"""
        return float(self.prize_amount - self.rake_amount())

    # --------------------------------------------------------
    # Serialización
    # --------------------------------------------------------

    def to_dict_basic(self) -> dict:
        """Resumen simple para handlers o API"""
        return {
            "id": self.id,
            "uuid": str(self.uuid),
            "challenger_id": self.challenger_id,
            "opponent_id": self.opponent_id,
            "bet_amount": float(self.bet_amount),
            "prize_amount": float(self.prize_amount),
            "status": self.status,
            "game": self.game_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    def to_dict_full(self) -> dict:
        """Detalles completos para administración"""
        basic = self.to_dict_basic()
        basic.update({
            "rake_percentage": float(self.rake_percentage),
            "total_pot": float(self.total_pot),
            "game_mode": self.game_mode,
            "game_link": self.game_link,
            "winner_id": self.winner_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_message_id": self.telegram_message_id,
        })
        return basic

    def __repr__(self) -> str:
        return (
            f"<Challenge(id={self.id}, "
            f"challenger={self.challenger_id}, "
            f"opponent={self.opponent_id}, "
            f"bet=${self.bet_amount}, "
            f"status={self.status})>"
        )
