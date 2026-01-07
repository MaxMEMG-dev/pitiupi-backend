# ============================================================
# database/services/payments_service.py — PITIUPI V6
# Servicios de depósitos (PaymentIntents)
# ============================================================

from decimal import Decimal
from typing import Tuple, List, Optional
from sqlalchemy.orm import Session

from database.models.payment_intents import PaymentIntent, PaymentIntentStatus
from database.models.transactions import TransactionType

# CRUDs
from database.crud import payments_crud
from database.crud import user_crud

# Services
from database.services import users_service


# ============================================================
# V6 ARCHITECTURE PRINCIPLES
# ============================================================
# 1. payments_service NO hace HTTP externo
# 2. payments_service NO llama directamente al ledger
# 3. users_service.add_balance() YA escribe en ledger automáticamente
# 4. NO capturamos snapshots de balance (responsabilidad de users_service)
# 5. Retiros están en withdrawals_service.py (separación de concerns)
# ============================================================


# ============================================================
# USER — Crear PaymentIntent para depósito
# ============================================================

def create_payment_intent_service(
    user_id: int,
    amount: float,
    session: Session,
) -> dict:
    """
    Crea un PaymentIntent pending.
    """
    amount_dec = Decimal(str(amount))

    # ✅ CORRECCIÓN: get_by_id con parámetros en orden correcto
    user = user_crud.get_by_id(session, user_id)
    
    if not user:
        raise ValueError(f"Usuario {user_id} no encontrado")

    # Crear PaymentIntent vía CRUD
    intent = payments_crud.create_payment_intent(
        session=session,
        user_id=user_id,
        provider="nuvei",
        provider_intent_id=None,
        amount=amount_dec,
        currency="USD",
        status=PaymentIntentStatus.PENDING,
        details={},
    )

    session.flush()

    return {
        "uuid": str(intent.uuid),
        "id": intent.id,
        "amount": float(amount_dec),
        # ✅ Retornamos None explícitamente porque el Backend se encargará de generarla
        "redirect_url": None 
    }

# ============================================================
# WEBHOOK — Confirmación de pago desde Nuvei
# ============================================================

def confirm_payment(
    intent_uuid: str,
    amount_received: Decimal,
    session: Session
) -> dict:
    """
    Confirma depósito desde webhook de pitiupi-backend.
    
    ✅ NUEVA FUNCIONALIDAD:
    - Marca primer depósito si es la primera vez
    - Retorna user_id y first_deposit flag
    - Actualiza user.status a ACTIVE si es primer depósito
    
    ⚠️ V6 CRITICAL FLOW:
    1. Validar PaymentIntent existe y está pending
    2. users_service.add_balance() ← ÚNICA mutación financiera
       └─> Esto YA escribe en el ledger automáticamente
    3. Marcar primer depósito si corresponde
    4. Marcar intent como completed
    """
    
    # Importaciones necesarias para nueva funcionalidad
    from database.models.user import UserStatus
    from database.utils import now_utc
    import logging
    
    logger = logging.getLogger(__name__)
    
    # 1. Obtener intent
    intent = payments_crud.get_by_uuid(intent_uuid, session=session)
    if not intent:
        raise ValueError(f"PaymentIntent {intent_uuid} no encontrado")

    # 2. Idempotencia: ignorar si ya completado
    if intent.status == PaymentIntentStatus.COMPLETED:
        logger.info(f"⚠️ PaymentIntent {intent_uuid} ya completado, ignorando")
        return {
            "status": "ignored", 
            "reason": "already_completed",
            "user_id": intent.user_id
        }

    # 3. Validar estado
    if intent.status != PaymentIntentStatus.PENDING:
        raise ValueError(f"PaymentIntent en estado inválido: {intent.status}")

    # 4. Validar usuario existe
    user = user_crud.get_by_id(session=session, user_id=intent.user_id)
    if not user:
        raise ValueError(f"Usuario {intent.user_id} no encontrado")
    
    # Guardar estado previo para determinar si es primer depósito
    was_first_deposit_completed = user.first_deposit_completed
    was_user_status = user.status

    # ============================================================
    # V6 FINANCIAL FLOW (ATÓMICO) + ONBOARDING
    # ============================================================
    
    # 5. Ejecutar mutación financiera (balance + ledger)
    users_service.add_balance(
        user_id=intent.user_id,
        amount=amount_received,
        session=session,
        description=f"Depósito vía Nuvei - Intent {intent_uuid}",
        related_id=intent.id,
        details={
            "source": "nuvei",
            "intent_uuid": intent_uuid,
            "provider": "nuvei",
            "is_first_deposit": not was_first_deposit_completed
        }
    )
    
    # 6. ✅ MARCAR PRIMER DEPÓSITO SI ES PRIMERA VEZ
    if not was_first_deposit_completed:
        user.first_deposit_completed = True
        user.first_deposit_at = now_utc()
        user.status = UserStatus.ACTIVE
        
        logger.info(f"✅ Primer depósito completado: user_id={user.id}, telegram_id={user.telegram_id}")
    
    # 7. Actualizar timestamps del usuario
    user.last_active_at = now_utc()
    user.updated_at = now_utc()
    
    # 8. Marcar intent como completado
    intent.status = PaymentIntentStatus.COMPLETED
    intent.amount_received = amount_received
    intent.completed_at = now_utc()
    session.flush()
    
    # 9. Log detallado
    logger.info(
        f"✅ Pago confirmado: intent={intent_uuid}, "
        f"user={user.id}, "
        f"amount=${float(amount_received)}, "
        f"first_deposit={not was_first_deposit_completed}, "
        f"prev_status={was_user_status}, "
        f"new_status={user.status}"
    )

    return {
        "status": "completed",
        "amount": float(amount_received),
        "user_id": user.id,
        "first_deposit": not was_first_deposit_completed,
        "user_status": user.status.value,
        "balance_available": float(user.balance_available)
    }

# ============================================================
# QUERIES — PaymentIntents (solo lectura)
# ============================================================

def get_payment_intent_by_uuid(
    intent_uuid: str,
    session: Session
) -> Optional[PaymentIntent]:
    """Obtiene un PaymentIntent por UUID."""
    return payments_crud.get_by_uuid(intent_uuid, session=session)


def list_user_payment_intents(
    user_id: int,
    session: Session,
    limit: int = 10
) -> List[PaymentIntent]:
    """Lista PaymentIntents de un usuario (metadata de pasarela)."""
    return payments_crud.list_by_user(
        user_id=user_id,
        session=session,
        limit=limit
    )


# ============================================================
# ADMIN — Depósitos paginados
# ============================================================

def admin_list_deposits_paginated(
    page: int,
    session: Session,
    page_size: int = 10
) -> Tuple[List[PaymentIntent], int]:
    """
    Lista PaymentIntents paginados (vista administrativa).
    
    Note:
        - PaymentIntents = metadata de pasarela de pago
        - Para historial financiero completo usar transactions_service
    """
    deposits, total = payments_crud.list_payment_intents_paginated(
        page=page,
        page_size=page_size,
        session=session,
    )
    
    total_pages = max(1, (total + page_size - 1) // page_size)
    return deposits, total_pages


def get_payment_intent_by_provider_order_id(
    provider_order_id: str,
    session: Session
) -> Optional[PaymentIntent]:
    """
    Busca un intento de pago por el ID de orden que devuelve la pasarela (Nuvei).
    Evita errores de sintaxis UUID en PostgreSQL.
    """
    return session.query(PaymentIntent).filter(
        PaymentIntent.provider_order_id == provider_order_id
    ).first()
