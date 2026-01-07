# ============================================================
# database/services/transactions_service.py
# Ledger de transacciones — PITIUPI V6
# Solo registra eventos, nunca valida ni muta balances
# ✅ CORREGIDO: Sin TransactionStatus, imports limpios
# ============================================================

import logging
from decimal import Decimal
from typing import List, Optional, Tuple
from datetime import datetime

from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from database.models.transactions import Transaction, TransactionType
from database.utils import now_utc, to_decimal

logger = logging.getLogger(__name__)


# ============================================================
# V6 CORE PRINCIPLE
# ============================================================
# El ledger es un registro histórico APPEND-ONLY.
# - NO valida matemáticas
# - NO reconstruye balances
# - NO muta estado
# - Solo escribe lo que users_service le dice que pasó
# ============================================================


def create_transaction(
    session: Session,
    user_id: int,
    type: TransactionType,
    amount: Decimal,
    description: str,
    related_id: Optional[int] = None,
    details: Optional[dict] = None,
) -> Transaction:
    """
    Registra un evento financiero en el ledger.
    
    ⚠️ V6 GOLDEN RULE:
    Esta función NO valida, NO calcula, NO decide.
    Solo REGISTRA lo que users_service ya ejecutó.
    
    ✅ CORRECCIONES V6:
    - NO acepta `status` (siempre es completada)
    - Usa `reference_id` en lugar de `related_id` internamente
    - Usa TransactionType sin .value
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        type: Tipo de transacción (TransactionType constant)
        amount: Impacto en balance_total
                - Positivo: depósitos, premios, reembolsos
                - Negativo: retiros, pérdidas
                - Cero: operaciones internas (freeze/unfreeze)
        description: Texto legible del evento
        related_id: ID de entidad relacionada (challenge_id, payment_id, etc)
        details: JSON con contexto adicional
        
    Returns:
        Transaction: Registro creado
        
    Example:
        # Después de users_service.add_balance()
        create_transaction(
            session,
            user_id=10,
            type=TransactionType.DEPOSIT,
            amount=Decimal("100.00"),
            description="Depósito vía Nuvei",
            related_id=payment_intent_id,
            details={"payment_method": "card_xxxx"}
        )
    """
    amount = to_decimal(amount)
    
    # ✅ CORREGIDO: usar reference_id (coincide con modelo)
    transaction = Transaction(
        user_id=user_id,
        type=type,  # ✅ CORREGIDO: ya es string, no usar .value
        amount=amount,
        description=description,
        reference_type="generic" if related_id else None,
        reference_id=str(related_id) if related_id else None,
        details=details or {},
        created_at=now_utc(),
    )
    
    session.add(transaction)
    session.flush()  # Para obtener transaction.id sin commit
    
    logger.info(
        f"📝 Transaction logged: id={transaction.id}, "
        f"user={user_id}, type={type}, amount={amount}"
    )
    
    return transaction


# ============================================================
# CONSULTAS (Read-only)
# ============================================================

def get_transaction_by_id(
    session: Session,
    transaction_id: int
) -> Optional[Transaction]:
    """Obtiene una transacción por ID."""
    return session.get(Transaction, transaction_id)


def list_transactions_by_user(
    session: Session,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    type: Optional[str] = None,
) -> List[Transaction]:
    """
    Lista transacciones de un usuario (más recientes primero).
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        limit: Máximo de resultados
        offset: Offset para paginación
        type: Filtrar por tipo (opcional)
        
    Returns:
        Lista de transacciones
    """
    query = select(Transaction).where(Transaction.user_id == user_id)
    
    if type:
        query = query.where(Transaction.type == type)
    
    query = query.order_by(desc(Transaction.created_at)).limit(limit).offset(offset)
    
    result = session.execute(query)
    return list(result.scalars().all())


def count_transactions_by_user(
    session: Session,
    user_id: int,
    type: Optional[str] = None,
) -> int:
    """Cuenta transacciones de un usuario."""
    query = select(func.count(Transaction.id)).where(
        Transaction.user_id == user_id
    )
    
    if type:
        query = query.where(Transaction.type == type)
    
    result = session.execute(query)
    return result.scalar() or 0


def get_user_transactions_page(
    session: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    type: Optional[str] = None,
) -> Tuple[List[Transaction], int]:
    """
    Obtiene una página de transacciones (para UI).
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        page: Número de página (1-indexed)
        page_size: Transacciones por página
        type: Filtrar por tipo (opcional)
        
    Returns:
        Tupla de (transacciones, total_pages)
    """
    if page < 1:
        page = 1
    
    offset = (page - 1) * page_size
    
    total = count_transactions_by_user(session, user_id, type)
    total_pages = max(1, (total + page_size - 1) // page_size)
    
    transactions = list_transactions_by_user(
        session,
        user_id=user_id,
        limit=page_size,
        offset=offset,
        type=type,
    )
    
    return transactions, total_pages


# ============================================================
# REPORTES (solo lectura, no validación)
# ============================================================

def get_user_transaction_summary(
    session: Session,
    user_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """
    Genera un resumen estadístico de transacciones.
    
    ⚠️ IMPORTANTE V6:
    Este es un REPORTE, no una validación.
    No se usa para verificar balances (eso es responsabilidad de users_service).
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        start_date: Fecha inicio (opcional)
        end_date: Fecha fin (opcional)
        
    Returns:
        Dict con métricas agregadas:
        {
            "total_deposits": Decimal,
            "total_withdrawals": Decimal,
            "total_wins": Decimal,
            "total_refunds": Decimal,
            "transaction_count": int,
            "net_impact": Decimal  # Solo informativo
        }
    """
    query = select(
        Transaction.type,
        func.sum(Transaction.amount).label("total"),
        func.count(Transaction.id).label("count")
    ).where(
        Transaction.user_id == user_id
    )
    
    if start_date:
        query = query.where(Transaction.created_at >= start_date)
    if end_date:
        query = query.where(Transaction.created_at <= end_date)
    
    query = query.group_by(Transaction.type)
    
    result = session.execute(query)
    rows = result.all()
    
    summary = {
        "total_deposits": Decimal("0.00"),
        "total_withdrawals": Decimal("0.00"),
        "total_wins": Decimal("0.00"),
        "total_refunds": Decimal("0.00"),
        "transaction_count": 0,
    }
    
    for row in rows:
        tx_type, total, count = row
        total = to_decimal(total or 0)
        
        summary["transaction_count"] += count
        
        if tx_type == TransactionType.DEPOSIT:
            summary["total_deposits"] = total
        elif tx_type == TransactionType.WITHDRAWAL:
            summary["total_withdrawals"] = abs(total)
        elif tx_type in [TransactionType.BET_WIN, TransactionType.CHALLENGE_WIN]:
            summary["total_wins"] = total
    
    # Net impact (solo informativo, NO es source of truth)
    summary["net_impact"] = (
        summary["total_deposits"]
        + summary["total_wins"]
        - summary["total_withdrawals"]
    )
    
    return summary


# ============================================================
# EXPORTACIONES PÚBLICAS
# ============================================================

__all__ = [
    # Core
    "create_transaction",
    
    # Queries
    "get_transaction_by_id",
    "list_transactions_by_user",
    "count_transactions_by_user",
    "get_user_transactions_page",
    
    # Reports
    "get_user_transaction_summary",
]
