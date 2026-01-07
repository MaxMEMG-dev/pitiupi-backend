# ============================================================
# database/services/withdrawals_service.py — PITIUPI V6.1 AML
# Servicios de retiros con separación balance_recharge/withdrawable
# ============================================================

from decimal import Decimal
from typing import Tuple, List, Optional
from sqlalchemy.orm import Session

from database.models.withdrawals import WithdrawalRequest, WithdrawalStatus
from database.models.user import User

# CRUDs
from database.crud import withdrawals_crud

# Services
from database.services.users_service import (
    get_user_by_id,
    freeze_balance,
    freeze_withdrawal_balance,
    unfreeze_balance
)


# ============================================================
# V6.1 AML ARCHITECTURE PRINCIPLES
# ============================================================
# 1. Solo balance_withdrawable es retirable (ganancias)
# 2. balance_recharge NO es retirable (depósitos)
# 3. freeze_balance() drena en orden: recharge → withdrawable → locked
# 4. Retiros SOLO deben drenar de balance_withdrawable
# 5. Si se rechaza, vuelve a balance_withdrawable (no recharge)
# ============================================================


# ============================================================
# HELPERS — Concurrency Control
# ============================================================

def _get_withdrawal_for_update(
    session: Session,
    withdraw_id: int
) -> Optional[WithdrawalRequest]:
    """
    Obtiene un WithdrawalRequest con bloqueo FOR UPDATE.
    
    ⚠️ CRITICAL:
    Previene race conditions cuando múltiples admins
    intentan procesar el mismo retiro simultáneamente.
    
    Args:
        session: Sesión SQLAlchemy
        withdraw_id: ID del retiro
    
    Returns:
        WithdrawalRequest bloqueado o None
    """
    from sqlalchemy import select
    
    stmt = (
        select(WithdrawalRequest)
        .where(WithdrawalRequest.id == withdraw_id)
        .with_for_update()  # ← Bloqueo pesimista
    )
    
    result = session.execute(stmt)
    return result.scalar_one_or_none()


# ============================================================
# USER — Solicitar retiro
# ============================================================

def request_withdrawal(
    user_id: int,
    amount: Decimal,
    method: str,
    details: str,
    session: Session,
) -> WithdrawalRequest:
    """
    ✅ V6.1 AML: Solicita un retiro (congela SOLO balance_withdrawable).
    """
    # Validar usuario existe
    user = get_user_by_id(session, user_id)
    if not user:
        raise ValueError(f"Usuario {user_id} no encontrado")

    # ✅ CRÍTICO V6.1 AML: Validar balance_withdrawable (no balance_available)
    if user.balance_withdrawable < amount:
        raise ValueError(
            f"Solo puedes retirar ganancias. "
            f"Balance retirable: ${user.balance_withdrawable}, "
            f"Balance de depósitos (no retirable): ${user.balance_recharge}, "
            f"Solicitado: ${amount}"
        )

    # ✅ NUEVO V6.1: Usamos la función específica para retiros
    # Esto asegura que NUNCA se toque el balance_recharge
    freeze_withdrawal_balance(
        session=session,
        user_id=user_id,
        amount=amount
    )

    # Crear WithdrawalRequest
    withdrawal = withdrawals_crud.create_withdrawal_request(
        session=session,
        user_id=user_id,
        amount=amount,
        method=method,
        details=details,
    )

    session.flush()
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f"💸 Solicitud de retiro creada: "
        f"user_id={user_id}, amount=${amount}, method={method}, "
        f"withdrawal_id={withdrawal.id}"
    )
    
    return withdrawal


# ============================================================
# ADMIN — Aprobar retiro
# ============================================================

def admin_approve_withdrawal(
    withdraw_id: int,
    admin_id: int,
    session: Session
) -> Tuple[bool, str]:
    """
    ✅ V6.1 AML: Aprueba un retiro (consume fondos bloqueados).
    
    Flow:
    1. Obtener retiro con FOR UPDATE (bloqueo de concurrencia)
    2. Validar estado (con idempotencia)
    3. Consumir balance_locked (sin devolver a ningún lado)
    4. Marcar WithdrawalRequest como APPROVED
    
    ⚠️ IDEMPOTENCIA:
    - Si ya está APPROVED → retorna éxito (safe retry)
    - Si está DECLINED → retorna error (no reversible)
    
    Args:
        withdraw_id: ID del retiro
        admin_id: ID del admin que aprueba
        session: Sesión SQLAlchemy
    
    Returns:
        Tuple[success, message]
    """
    from sqlalchemy import select
    import logging
    logger = logging.getLogger(__name__)
    
    # Obtener retiro con bloqueo de concurrencia
    wd = _get_withdrawal_for_update(session, withdraw_id)
    if not wd:
        return False, "Solicitud no encontrada"

    # ============================================================
    # IDEMPOTENCIA: Permitir reintentos seguros
    # ============================================================
    if wd.status == WithdrawalStatus.APPROVED:
        return True, "Retiro ya estaba aprobado (idempotente)"
    
    if wd.status == WithdrawalStatus.DECLINED:
        return False, "No se puede aprobar un retiro rechazado"
    
    if wd.status != WithdrawalStatus.REQUESTED:
        return False, f"Estado inválido: {wd.status}"

    # Validar usuario existe y obtener con bloqueo
    stmt = select(User).where(User.id == wd.user_id).with_for_update()
    user = session.execute(stmt).scalar_one_or_none()
    
    if not user:
        return False, "Usuario no encontrado"

    # Validar fondos locked (safety check)
    if user.balance_locked < wd.amount:
        return False, (
            f"Fondos bloqueados insuficientes. "
            f"Locked: ${user.balance_locked}, Required: ${wd.amount}"
        )

    # ✅ Consumir balance_locked (el dinero sale del sistema)
    user.balance_locked -= wd.amount
    user.recalculate_total()
    
    session.add(user)
    
    # Actualizar estado del retiro
    withdrawals_crud.update_withdrawal_status(
        session=session,
        withdrawal=wd,
        status=WithdrawalStatus.APPROVED,
        processed_by=admin_id,
    )
    
    session.flush()
    
    logger.info(
        f"✅ Retiro aprobado: withdrawal_id={wd.id}, "
        f"user_id={wd.user_id}, amount=${wd.amount}, "
        f"approved_by={admin_id}"
    )

    return True, f"Retiro aprobado exitosamente. ${wd.amount} USD enviados."


# ============================================================
# ADMIN — Rechazar retiro
# ============================================================

def admin_reject_withdrawal(
    withdraw_id: int,
    admin_id: int,
    session: Session,
    reason: str = "Rechazado por administrador"
) -> Tuple[bool, str]:
    """
    ✅ V6.1 AML: Rechaza un retiro (devuelve fondos a balance_withdrawable).
    
    CRÍTICO:
    - Los fondos vuelven a balance_withdrawable (NO a recharge)
    - Esto permite que el usuario intente retirar de nuevo
    
    Flow:
    1. Validar estado REQUESTED
    2. Mover locked → withdrawable (manual, no usar unfreeze_balance)
    3. Marcar WithdrawalRequest como DECLINED
    
    Args:
        withdraw_id: ID del retiro
        admin_id: ID del admin que rechaza
        session: Sesión SQLAlchemy
        reason: Motivo del rechazo
    
    Returns:
        Tuple[success, message]
    """
    from sqlalchemy import select
    import logging
    logger = logging.getLogger(__name__)
    
    # Obtener retiro con bloqueo
    wd = _get_withdrawal_for_update(session, withdraw_id)
    if not wd:
        return False, "Solicitud no encontrada"

    # Validar estado
    if wd.status == WithdrawalStatus.DECLINED:
        return True, "Retiro ya estaba rechazado (idempotente)"
    
    if wd.status != WithdrawalStatus.REQUESTED:
        return False, f"Estado inválido: {wd.status}. Solo se pueden rechazar retiros REQUESTED"

    # Validar usuario existe y obtener con bloqueo
    stmt = select(User).where(User.id == wd.user_id).with_for_update()
    user = session.execute(stmt).scalar_one_or_none()
    
    if not user:
        return False, "Usuario no encontrado"

    # ✅ CRÍTICO V6.1 AML: Devolver a balance_withdrawable (NO a recharge)
    # Esto permite que el usuario intente retirar de nuevo
    user.balance_locked -= wd.amount
    user.balance_withdrawable += wd.amount  # ← Vuelve a retirable
    user.recalculate_total()
    
    session.add(user)
    
    # Actualizar estado del retiro
    withdrawals_crud.update_withdrawal_status(
        session=session,
        withdrawal=wd,
        status=WithdrawalStatus.DECLINED,
        processed_by=admin_id,
        reason=reason,
    )
    
    session.flush()
    
    logger.info(
        f"❌ Retiro rechazado: withdrawal_id={wd.id}, "
        f"user_id={wd.user_id}, amount=${wd.amount}, "
        f"reason={reason}, rejected_by={admin_id}"
    )

    return True, f"Retiro rechazado. ${wd.amount} devueltos a balance retirable."


# ============================================================
# QUERIES — WithdrawalRequests (solo lectura)
# ============================================================

def get_withdrawal_by_id(
    withdraw_id: int,
    session: Session
) -> Optional[WithdrawalRequest]:
    """Obtiene un retiro por ID."""
    return withdrawals_crud.get_withdrawal_by_id(withdraw_id, session)


def list_user_withdrawals(
    user_id: int,
    session: Session,
    status: Optional[WithdrawalStatus] = None,
    limit: int = 10
) -> List[WithdrawalRequest]:
    """Lista retiros de un usuario."""
    return withdrawals_crud.list_user_withdrawals(
        session=session,
        user_id=user_id,
        status=status,
        limit=limit
    )


def list_pending_withdrawals(session: Session) -> List[WithdrawalRequest]:
    """Lista todos los retiros pendientes (para admins)."""
    return withdrawals_crud.list_pending_withdrawals(session)


# ============================================================
# EXPORTACIONES
# ============================================================

__all__ = [
    "request_withdrawal",
    "admin_approve_withdrawal",
    "admin_reject_withdrawal",
    "get_withdrawal_by_id",
    "list_user_withdrawals",
    "list_pending_withdrawals",
]