# ============================================================
# database/services/users_service.py — PITIUPI V6.1
# Gestión de usuarios y balances (núcleo financiero)
# ✅ ACTUALIZADO: Separación balance_recharge / balance_withdrawable (AML)
# MILESTONE #1 - Funciones de onboarding agregadas
# ============================================================

import logging
from decimal import Decimal
from typing import Optional, List, Dict
from datetime import datetime

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from database.models.user import User, UserStatus
from database.utils import now_utc, to_decimal

logger = logging.getLogger(__name__)


# ============================================================
# HELPER: BLOQUEO DE FILA PARA CONCURRENCIA
# ============================================================

def _get_user_for_update(session: Session, user_id: int) -> User:
    """
    Obtiene un usuario con bloqueo de fila (SELECT ... FOR UPDATE).
    
    CRÍTICO V6: Previene race conditions en mutaciones concurrentes.
    
    Args:
        session: Sesión SQLAlchemy activa
        user_id: ID del usuario
        
    Returns:
        User con bloqueo de fila
        
    Raises:
        ValueError: Si usuario no existe
    """
    stmt = select(User).where(User.id == user_id).with_for_update()
    result = session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise ValueError(f"User not found: {user_id}")
    
    return user


# ============================================================
# NORMALIZACIÓN DE DATOS
# ============================================================

def _normalize_string(value: Optional[str]) -> Optional[str]:
    """
    Normaliza strings de entrada (trim + None si vacío).
    
    Args:
        value: String a normalizar
        
    Returns:
        String normalizado o None
    """
    if value is None:
        return None
    
    normalized = str(value).strip()
    return normalized if normalized else None


# ============================================================
# GET OR CREATE USER (MILESTONE #1 - UPDATED)
# ============================================================

def get_or_create_user(
    session: Session,
    telegram_id: str,
    telegram_username: Optional[str] = None,
    telegram_first_name: Optional[str] = None,
    telegram_last_name: Optional[str] = None,
    lang: Optional[str] = None,
) -> User:
    """
    Obtiene o crea un usuario por telegram_id.
    
    ⚠️ IMPORTANTE V6:
    - NO hace commit (responsabilidad del caller)
    - Solo crea si no existe
    - Actualiza last_active_at siempre
    - Usuario se crea con status PENDING (onboarding incompleto)
    - 🆕 Milestone #1: Acepta parámetro `lang`
    - ✅ V6.1: Balances separados (recharge + withdrawable)
    - ✅ V6.2: lang puede ser None para pedir selección de idioma
    
    Args:
        session: Sesión de SQLAlchemy
        telegram_id: ID de Telegram (único)
        telegram_username: Username de Telegram (opcional)
        telegram_first_name: Nombre de Telegram (opcional)
        telegram_last_name: Apellido de Telegram (opcional)
        lang: Idioma del usuario ('es', 'en', o None para pedir)
        
    Returns:
        User: Usuario existente o recién creado
        
    Example:
        with db_session() as session:
            user = get_or_create_user(session, "123456", "alice", lang=None)
            session.commit()  # ✅ Caller decide cuándo
    """
    # Normalizar inputs
    telegram_username = _normalize_string(telegram_username)
    telegram_first_name = _normalize_string(telegram_first_name)
    telegram_last_name = _normalize_string(telegram_last_name)
    
    # ✅ CORREGIDO: Validar idioma solo si se proporciona
    if lang is not None and lang not in ["es", "en"]:
        logger.warning(f"Idioma inválido '{lang}', usando 'es' como fallback")
        lang = "es"
    
    # Buscar usuario existente
    stmt = select(User).where(User.telegram_id == str(telegram_id))
    
    try:
        result = session.execute(stmt)
        user = result.scalar_one_or_none()
        
    except Exception as e:
        # Si hay error en la consulta, puede ser problema de mapeo
        logger.error(f"❌ Error ejecutando consulta en get_or_create_user: {e}")
        logger.error(f"   Telegram ID: {telegram_id}")
        logger.error(f"   Statement: {stmt}")
        
        # Intentar diagnóstico adicional
        try:
            # Probar si el modelo User está mapeado
            from sqlalchemy import inspect
            inspector = inspect(User)
            logger.error(f"   User mapper relaciones: {[rel.key for rel in inspector.relationships]}")
        except:
            pass
            
        # Re-lanzar el error para que el caller lo maneje
        raise
    
    if user:
        # Actualizar datos si están vacíos (merge de info de Telegram)
        updated = False
        
        if telegram_username and not user.telegram_username:
            user.telegram_username = telegram_username
            updated = True
        
        if telegram_first_name and not user.telegram_first_name:
            user.telegram_first_name = telegram_first_name
            updated = True
            
        if telegram_last_name and not user.telegram_last_name:
            user.telegram_last_name = telegram_last_name
            updated = True
        
        # Actualizar last_active siempre
        user.last_active_at = now_utc()
        user.updated_at = now_utc()
        
        # Flush siempre para persistir cambios de timestamps
        session.add(user)
        
        try:
            session.flush()
            if updated:
                logger.info(f"🔄 Usuario actualizado: telegram_id={telegram_id}, id={user.id}")
        except Exception as e:
            logger.error(f"❌ Error flushing usuario existente: {e}")
            # No re-lanzar aquí, el usuario ya existe y fue encontrado
            # Solo falló la actualización de timestamps
        
        return user
    
    # ✅ V6.2: Crear nuevo usuario permitiendo lang=None
    try:
        user = User(
            telegram_id=str(telegram_id),
            telegram_username=telegram_username,
            telegram_first_name=telegram_first_name,
            telegram_last_name=telegram_last_name,
            
            # Estado inicial (onboarding pendiente)
            status=UserStatus.PENDING,
            is_admin=False,
            is_verified=False,
            
            # ✅ CRÍTICO V6.2: lang puede ser None para pedir selección
            lang=lang,  # NO usar "lang or 'es'"
            
            # 🆕 Términos y depósito (Milestone #1)
            terms_accepted=False,
            first_deposit_completed=False,
            
            # ✅ V6.1: Balances iniciales separados (CRÍTICO AML)
            balance_recharge=Decimal("0.00"),      # Depósitos (No retirable)
            balance_withdrawable=Decimal("0.00"),  # Ganancias (Retirable)
            balance_locked=Decimal("0.00"),
            balance_total=Decimal("0.00"),
            
            # Timestamps
            created_at=now_utc(),
            updated_at=now_utc(),
            last_active_at=now_utc(),
        )
        
        session.add(user)
        session.flush()  # Para obtener user.id sin commit
        
        logger.info(f"✅ Usuario creado: telegram_id={telegram_id}, id={user.id}, lang={lang or 'None (pedirá selección)'}")
        
        return user
        
    except Exception as e:
        logger.error(f"❌ Error creando usuario: {e}")
        logger.error(f"   Datos: telegram_id={telegram_id}, username={telegram_username}")
        
        # Re-lanzar el error
        raise


# ============================================================
# OBTENER USUARIOS
# ============================================================

def get_user_by_telegram_id(session: Session, telegram_id: str) -> Optional[User]:
    """
    Obtiene un usuario por su ID de Telegram.
    Optimizado para evitar errores de mapeo en V6.1.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    try:
        stmt = (
            select(User)
            .where(User.telegram_id == str(telegram_id))
        )
        
        result = session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        import logging
        logging.error(f"Error crítico en get_user_by_telegram_id: {e}")
        return None


def get_user_by_id(
    session: Session,
    user_id: int
) -> Optional[User]:
    """
    Obtiene un usuario por ID interno.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID interno del usuario
        
    Returns:
        User o None si no existe
    """
    return session.get(User, user_id)


# ============================================================
# VALIDACIONES DE PERFIL Y ONBOARDING (MILESTONE #1)
# ============================================================

def is_profile_complete(user: User) -> bool:
    """
    Valida si el perfil del usuario está completo para participar.
    
    Requerimientos mínimos V6 (Milestone #1):
    - telegram_first_name
    - country
    - city
    - document_number
    - birthdate
    - email
    - phone
    
    Args:
        user: Usuario a validar
        
    Returns:
        bool: True si todos los campos están completos
    """
    required_fields = [
        user.telegram_first_name,
        user.country,
        user.city,
        user.document_number,
        user.birthdate,
        user.email,
        user.phone,
    ]
    
    return all(field is not None and str(field).strip() != "" for field in required_fields)


def has_accepted_terms(user: User) -> bool:
    """
    Verifica si el usuario ha aceptado términos y condiciones.
    
    Args:
        user: Usuario a validar
        
    Returns:
        bool: True si aceptó términos
    """
    return bool(user.terms_accepted)


def has_completed_first_deposit(user: User) -> bool:
    """
    Verifica si el usuario completó su primer depósito.
    
    Args:
        user: Usuario a validar
        
    Returns:
        bool: True si completó depósito
    """
    return bool(user.first_deposit_completed)


def can_access_platform(user: User) -> bool:
    """
    Verifica si el usuario puede acceder a la plataforma completa.
    
    Requisitos completos (Milestone #1):
    1. Perfil completo
    2. Términos aceptados
    3. Primer depósito realizado
    4. Status ACTIVE
    
    Args:
        user: Usuario a validar
        
    Returns:
        bool: True si cumple todos los requisitos
    """
    return (
        is_profile_complete(user) and
        has_accepted_terms(user) and
        has_completed_first_deposit(user) and
        user.status == UserStatus.ACTIVE
    )


# ============================================================
# ACTUALIZAR PERFIL (MILESTONE #1)
# ============================================================

def update_user_language(
    session: Session,
    telegram_id: str,
    lang: str
) -> Optional[User]:
    """
    Actualiza el idioma del usuario.
    
    Args:
        session: Sesión de SQLAlchemy
        telegram_id: ID de Telegram
        lang: Idioma ('es' o 'en')
        
    Returns:
        User actualizado o None si no existe
    """
    if lang not in ["es", "en"]:
        lang = "es"  # Fallback
    
    user = get_user_by_telegram_id(session, telegram_id)
    if not user:
        return None
    
    user.lang = lang
    user.updated_at = now_utc()
    
    session.add(user)
    session.flush()
    
    logger.info(f"✅ Idioma actualizado: user={telegram_id}, lang={lang}")
    
    return user


def accept_terms(
    session: Session,
    telegram_id: str
) -> Optional[User]:
    """
    Marca que el usuario aceptó términos y condiciones.
    
    Args:
        session: Sesión de SQLAlchemy
        telegram_id: ID de Telegram
        
    Returns:
        User actualizado o None si no existe
    """
    user = get_user_by_telegram_id(session, telegram_id)
    if not user:
        return None
    
    user.terms_accepted = True
    user.terms_accepted_at = now_utc()
    user.updated_at = now_utc()
    
    session.add(user)
    session.flush()
    
    logger.info(f"✅ Términos aceptados: user={telegram_id}")
    
    return user


def mark_first_deposit_completed(
    session: Session,
    user_id: int
) -> Optional[User]:
    """
    ✅ ACTUALIZADO: Marca que el usuario completó su primer depósito.
    También cambia el status a ACTIVE.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID interno del usuario (no telegram_id)
        
    Returns:
        User actualizado o None si no existe
    """
    user = _get_user_for_update(session, user_id)
    
    user.first_deposit_completed = True
    user.first_deposit_at = now_utc()
    user.status = UserStatus.ACTIVE
    user.updated_at = now_utc()
    
    session.add(user)
    session.flush()
    
    logger.info(f"✅ Primer depósito completado: user_id={user_id}, status=ACTIVE")
    
    return user


def complete_registration(session: Session, telegram_id: str) -> User:
    """
    Completa el registro del usuario validando que todos los campos requeridos estén presentes.
    
    Args:
        session: Sesión de SQLAlchemy
        telegram_id: ID de Telegram
        
    Returns:
        User actualizado
        
    Raises:
        ValueError: Si usuario no existe o perfil incompleto
    """
    user = session.query(User).filter_by(telegram_id=telegram_id).first()

    if not user:
        raise ValueError(f"Usuario no encontrado: telegram_id={telegram_id}")

    # ✅ CORREGIDO: Usar los nombres reales del modelo User.py
    missing_fields = []
    if not user.telegram_first_name: missing_fields.append("telegram_first_name")
    if not user.email: missing_fields.append("email")
    if not user.phone: missing_fields.append("phone")
    if not user.document_number: missing_fields.append("document_number")

    if missing_fields:
        raise ValueError(f"Perfil incompleto. Faltan: {', '.join(missing_fields)}")

    user.updated_at = datetime.utcnow()
    
    session.add(user)
    return user


# ============================================================
# GESTIÓN DE BALANCES V6.1 (AML COMPLIANCE)
# ============================================================

def get_user_balance_v6(session: Session, user_id: int) -> Dict[str, float]:
    """
    ✅ NUEVO V6.1: Retorna el desglose completo de saldos separados.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID interno del usuario
        
    Returns:
        dict con saldos: available_total, recharge, withdrawable, locked
        
    Example:
        {
            "available_total": 15.00,  # recharge + withdrawable
            "recharge": 10.00,         # Depósitos (No retirable)
            "withdrawable": 5.00,      # Ganancias (Retirable)
            "locked": 0.00             # En retos activos
        }
    """
    user = session.get(User, user_id)
    if not user:
        return {
            "available_total": 0.0,
            "recharge": 0.0,
            "withdrawable": 0.0,
            "locked": 0.0
        }
    
    return {
        "available_total": float(user.balance_available),  # Propiedad calculada
        "recharge": float(user.balance_recharge),
        "withdrawable": float(user.balance_withdrawable),
        "locked": float(user.balance_locked)
    }


def freeze_balance(session: Session, user_id: int, amount: Decimal) -> bool:
    """
    ✅ ACTUALIZADO V6.1: Bloquea saldo para un reto siguiendo jerarquía AML.
    
    Prioridad de gasto:
    1. Gasta primero de balance_recharge (Depósitos - No retirable)
    2. Si falta, gasta de balance_withdrawable (Ganancias - Retirable)
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        amount: Cantidad a bloquear
        
    Returns:
        bool: True si operación exitosa
        
    Raises:
        ValueError: Si saldo insuficiente o usuario no existe
        
    Example:
        # Usuario tiene: recharge=$8, withdrawable=$5
        freeze_balance(session, user_id, Decimal("10"))
        # Resultado: recharge=$0, withdrawable=$3, locked=$10
    """
    user = _get_user_for_update(session, user_id)
    amount = to_decimal(amount)

    # Validar saldo disponible total
    if user.balance_available < amount:
        raise ValueError(
            f"Saldo insuficiente. Disponible: ${user.balance_available}, "
            f"Solicitado: ${amount}"
        )

    remaining_to_freeze = amount

    # --- LÓGICA DE PRIORIDAD AML ---
    # 1. Intentar cobrar primero de lo NO retirable (recharge)
    if user.balance_recharge > 0:
        drain_from_recharge = min(user.balance_recharge, remaining_to_freeze)
        user.balance_recharge -= drain_from_recharge
        remaining_to_freeze -= drain_from_recharge
        
        logger.debug(
            f"Drenado ${drain_from_recharge} de balance_recharge. "
            f"Restante por congelar: ${remaining_to_freeze}"
        )

    # 2. Si aún falta, cobrar de las ganancias (withdrawable)
    if remaining_to_freeze > 0:
        if user.balance_withdrawable < remaining_to_freeze:
            # Esto no debería pasar si la validación inicial está bien
            raise ValueError(
                f"Error interno: balance_withdrawable insuficiente. "
                f"Necesario: ${remaining_to_freeze}, Disponible: ${user.balance_withdrawable}"
            )
        
        user.balance_withdrawable -= remaining_to_freeze
        
        logger.debug(
            f"Drenado ${remaining_to_freeze} de balance_withdrawable"
        )

    # 3. Pasar el dinero al contenedor de seguridad (locked)
    user.balance_locked += amount
    
    # 4. Recalcular el total (recharge + withdrawable + locked)
    user.recalculate_total()
    
    session.add(user)
    session.flush()
    
    logger.info(
        f"💰 Saldo congelado para user {user_id}: ${amount} "
        f"(Prioridad: Recharge primero)"
    )
    
    return True

def freeze_withdrawal_balance(session: Session, user_id: int, amount: Decimal) -> bool:
    """
    ✅ NUEVO V6.1 AML: Bloquea saldo ESPECÍFICAMENTE para retiros.
    
    A diferencia de freeze_balance (que prioriza recharge), esta función
    solo puede drenar de balance_withdrawable, ya que es el único saldo
    legalmente retirable.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        amount: Cantidad a retirar
        
    Returns:
        bool: True si operación exitosa
        
    Raises:
        ValueError: Si el saldo retirable es insuficiente
    """
    user = _get_user_for_update(session, user_id)
    amount = to_decimal(amount)

    # VALIDACIÓN CRÍTICA AML: Solo puede retirar de balance_withdrawable
    if user.balance_withdrawable < amount:
        raise ValueError(
            f"Saldo retirable insuficiente. "
            f"Disponible para retiro: ${user.balance_withdrawable}, "
            f"Solicitado: ${amount}"
        )

    # 1. Restar del saldo retirable
    user.balance_withdrawable -= amount
    
    # 2. Mover al contenedor de seguridad (locked) hasta que Runa/Admin apruebe
    user.balance_locked += amount
    
    # 3. Recalcular total (total sigue siendo el mismo, pero cambia la distribución)
    user.recalculate_total()
    
    session.add(user)
    session.flush()
    
    logger.info(
        f"🏦 Saldo bloqueado para RETIRO: user {user_id}, monto ${amount} "
        f"(Drenado de balance_withdrawable)"
    )
    
    return True


def unfreeze_balance(session: Session, user_id: int, amount: Decimal) -> bool:
    """
    ✅ ACTUALIZADO V6.1: Libera saldo bloqueado (ej. reto cancelado).
    
    Política de seguridad AML:
    - El dinero liberado vuelve a balance_recharge para asegurar que se use en otro juego.
    - Esto previene el "lavado" mediante cancelaciones repetidas.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        amount: Cantidad a liberar
        
    Returns:
        bool: True si operación exitosa
        
    Raises:
        ValueError: Si usuario no existe
        
    Example:
        # Usuario tiene: locked=$10
        unfreeze_balance(session, user_id, Decimal("10"))
        # Resultado: locked=$0, recharge=$10 (debe jugarlo de nuevo)
    """
    user = _get_user_for_update(session, user_id)
    amount = to_decimal(amount)

    # Ajustar cantidad si excede lo bloqueado
    if user.balance_locked < amount:
        logger.warning(
            f"Se intentó liberar ${amount} pero solo hay ${user.balance_locked} bloqueado. "
            f"Liberando todo lo disponible."
        )
        amount = user.balance_locked

    # Liberar del locked
    user.balance_locked -= amount
    
    # ✅ Política AML: Devolver a recharge para que deba jugarse de nuevo
    user.balance_recharge += amount
    
    # Recalcular total
    user.recalculate_total()
    
    session.add(user)
    session.flush()
    
    logger.info(
        f"🔓 Saldo liberado para user {user_id}: ${amount} "
        f"(Devuelto a balance_recharge)"
    )
    
    return True


def transfer_prize_to_winner(session: Session, winner_id: int, prize_amount: Decimal) -> bool:
    """
    ✅ ACTUALIZADO V6.1: Entrega premio al ganador.
    
    CRÍTICO AML:
    - TODO el dinero ganado se deposita en balance_withdrawable (retirable)
    - Esto "limpia" el dinero: ya puede ser retirado
    
    Args:
        session: Sesión de SQLAlchemy
        winner_id: ID del ganador
        prize_amount: Monto del premio
        
    Returns:
        bool: True si operación exitosa
        
    Raises:
        ValueError: Si usuario no existe
        
    Example:
        # Ganador gana $20 de un reto
        transfer_prize_to_winner(session, winner_id, Decimal("20"))
        # Resultado: withdrawable += $20 (PUEDE RETIRARLO)
    """
    winner = _get_user_for_update(session, winner_id)
    prize_amount = to_decimal(prize_amount)

    # ✅ El dinero ganado SIEMPRE va a la columna de retirables
    winner.balance_withdrawable += prize_amount
    
    # Actualizar estadísticas para el perfil
    winner.total_wins += prize_amount
    
    # Recalcular total
    winner.recalculate_total()
    
    session.add(winner)
    session.flush()
    
    logger.info(
        f"🏆 Premio de ${prize_amount} entregado a user {winner_id} "
        f"como SALDO RETIRABLE (balance_withdrawable)"
    )
    
    return True


def add_recharge_balance(session: Session, user_id: int, amount: Decimal) -> bool:
    """
    ✅ NUEVO V6.1: Agrega saldo de recarga (depósitos).
    
    Este método debe ser llamado por el webhook de pagos.
    El dinero depositado NO es retirable hasta que se gane en un reto.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        amount: Cantidad depositada
        
    Returns:
        bool: True si operación exitosa
        
    Raises:
        ValueError: Si usuario no existe o amount inválido
    """
    user = _get_user_for_update(session, user_id)
    amount = to_decimal(amount)
    
    if amount <= 0:
        raise ValueError(f"El monto debe ser mayor a 0: ${amount}")
    
    # Agregar al balance de recargas (No retirable)
    user.balance_recharge += amount
    
    # Actualizar estadísticas
    user.total_deposits += amount
    
    # Recalcular total
    user.recalculate_total()
    
    session.add(user)
    session.flush()
    
    logger.info(
        f"💳 Recarga agregada para user {user_id}: ${amount} "
        f"(balance_recharge - NO retirable hasta ganar)"
    )
    
    return True


def add_balance(session: Session, user_id: int, amount: Decimal, is_win: bool = False) -> bool:
    """
    ✅ WRAPPER de compatibilidad: Agrega saldo (depósito o ganancia).
    
    Deprecado en favor de add_recharge_balance() y transfer_prize_to_winner().
    Mantenido para compatibilidad con código legacy.
    
    Args:
        session: Sesión de SQLAlchemy
        user_id: ID del usuario
        amount: Cantidad a agregar
        is_win: Si es ganancia (True) o depósito (False)
        
    Returns:
        bool: True si operación exitosa
    """
    if is_win:
        return transfer_prize_to_winner(session, user_id, amount)
    else:
        return add_recharge_balance(session, user_id, amount)


# ============================================================
# EXPORTACIONES PÚBLICAS
# ============================================================

__all__ = [
    # Get/Create
    "get_or_create_user",
    "get_user_by_telegram_id",
    "get_user_by_id",
    
    # Validations (Milestone #1)
    "is_profile_complete",
    "has_accepted_terms",
    "has_completed_first_deposit",
    "can_access_platform",
    
    # Updates (Milestone #1)
    "update_user_language",
    "accept_terms",
    "mark_first_deposit_completed",
    "complete_registration",
    
    # Balance Management V6.1 (AML)
    "get_user_balance_v6",
    "freeze_balance",
    "freeze_withdrawal_balance",
    "unfreeze_balance",
    "transfer_prize_to_winner",
    "add_recharge_balance",
    "add_balance",  # Legacy wrapper
]
