# ============================================================
# database/services/challenges_service.py — PITIUPI v5.0
# Lógica de negocio completa para el sistema de Retos/Duelos
# Arquitectura: Handlers → Services → CRUD
# ============================================================

from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession  # ➕ ADD

from database.session import async_session
from database.models.challenges import Challenge, ChallengeStatus  # 🔧 FIX
from database.models.user import User, UserStatus
from database.crud.challenges_crud import ChallengesCRUD
from database.services.users_service import (
    freeze_balance,
    unfreeze_balance,
    transfer_prize_to_winner,
    get_user_balance,
)
from database.utils import now_utc

# ============================================================
# Configuración financiera
# ============================================================

# Rake fijo según MVP: 10%
RAKE_PERCENTAGE = Decimal("0.10")


# ============================================================
# Crear desafío
# ============================================================

async def create_challenge(
    challenger_id: int,
    game_name: str,
    game_mode: str,
    amount: Decimal,
    opponent_id: Optional[int] = None,
    game_link: Optional[str] = None,
) -> int:
    """
    Crea un nuevo desafío con estado OPEN.

    - Valida usuario y monto
    - Calcula pot y premio
    - Congela saldo del creador (transaccional)
    - NO publica (eso es responsabilidad del handler)
    """

    if amount <= Decimal("0"):
        raise ValueError("El monto debe ser mayor a 0")

    async with async_session() as session:
        # ----------------------------------------------------
        # Validar usuario creador
        # ----------------------------------------------------
        challenger = await session.get(User, challenger_id)
        if not challenger or challenger.status != UserStatus.ACTIVE:
            raise ValueError("Usuario no activo")

        # ----------------------------------------------------
        # Validar saldo
        # ----------------------------------------------------
        current_balance = await get_user_balance(challenger_id)
        if current_balance < amount:
            raise ValueError("Saldo insuficiente")

        # ----------------------------------------------------
        # Validar oponente si es reto privado
        # ----------------------------------------------------
        if opponent_id is not None:
            opponent = await session.get(User, opponent_id)
            if not opponent or opponent.status != UserStatus.ACTIVE:
                raise ValueError("Oponente no válido o no activo")

        # ----------------------------------------------------
        # Cálculos financieros
        # ----------------------------------------------------
        total_pot = amount * Decimal("2")
        prize_amount = total_pot * (Decimal("1") - RAKE_PERCENTAGE)

        # ----------------------------------------------------
        # Congelar saldo del creador
        # ----------------------------------------------------
        await freeze_balance(
            challenger_id,
            amount,
            session=session,
        )

        # ----------------------------------------------------
        # Crear desafío
        # ----------------------------------------------------
        challenge_id = await ChallengesCRUD.create(
            session=session,
            challenger_id=challenger_id,
            opponent_id=opponent_id,
            bet_amount=amount,
            rake_percentage=RAKE_PERCENTAGE,
            total_pot=total_pot,
            prize_amount=prize_amount,
            game_name=game_name,
            game_mode=game_mode,
            game_link=game_link or "",
            status=ChallengeStatus.OPEN,
            expires_at=now_utc() + timedelta(minutes=30),
        )

        await session.commit()
        return challenge_id


# ============================================================
# Aceptar desafío
# ============================================================

async def accept_challenge(challenge_id: int, user_id: int) -> str:
    """
    Acepta un desafío OPEN.
    """

    async with async_session() as session:
        challenge = await ChallengesCRUD.get(session, challenge_id)

        if not challenge:
            return "❌ Este desafío ya no existe."

        if challenge.status != ChallengeStatus.OPEN:
            return "❌ Este desafío ya no está disponible."

        if challenge.challenger_id == user_id:
            return "❌ No puedes aceptar tu propio reto."

        if challenge.expires_at and challenge.expires_at < now_utc():
            return "❌ Este desafío ha expirado."

        # Protección para retos privados
        if challenge.opponent_id is not None and challenge.opponent_id != user_id:
            return "❌ No estás autorizado a aceptar este desafío."

        # Validar saldo del aceptador
        current_balance = await get_user_balance(user_id)
        if current_balance < challenge.bet_amount:
            return f"❌ Saldo insuficiente. Necesitas {challenge.bet_amount}."

        # Congelar saldo del aceptador
        await freeze_balance(
            user_id,
            challenge.bet_amount,
            session=session,
        )

        # Actualizar desafío
        await ChallengesCRUD.update(
            session=session,
            challenge_id=challenge_id,
            opponent_id=user_id,
            status=ChallengeStatus.MATCHED,
            started_at=now_utc(),
        )

        await session.commit()
        return "✅ ¡Desafío aceptado! Los fondos han sido congelados."


# ============================================================
# Rechazar desafío (solo privados)
# ============================================================

async def reject_challenge(challenge_id: int, user_id: int) -> str:
    """
    Rechaza un desafío privado OPEN.
    """

    async with async_session() as session:
        challenge = await ChallengesCRUD.get(session, challenge_id)

        if not challenge:
            return "❌ Este desafío ya no existe."

        if challenge.status != ChallengeStatus.OPEN:
            return "❌ Este desafío ya no está disponible."

        if challenge.opponent_id is None:
            return "❌ Solo se pueden rechazar desafíos privados."

        if challenge.opponent_id != user_id:
            return "❌ No estás autorizado a rechazar este desafío."

        # Liberar saldo del creador
        await unfreeze_balance(
            challenge.challenger_id,
            challenge.bet_amount,
            session=session,
        )

        await ChallengesCRUD.update(
            session=session,
            challenge_id=challenge_id,
            status=ChallengeStatus.CANCELLED,
        )

        await session.commit()
        return "❌ Has rechazado el desafío."


# ============================================================
# Expirar desafío
# ============================================================

async def expire_challenge(challenge_id: int) -> None:
    """
    Expira automáticamente un desafío OPEN vencido.
    """

    async with async_session() as session:
        challenge = await ChallengesCRUD.get(session, challenge_id)

        if not challenge or challenge.status != ChallengeStatus.OPEN:
            return

        await unfreeze_balance(
            challenge.challenger_id,
            challenge.bet_amount,
            session=session,
        )

        await ChallengesCRUD.update(
            session=session,
            challenge_id=challenge_id,
            status=ChallengeStatus.EXPIRED,
        )

        await session.commit()


# ============================================================
# Completar desafío
# ============================================================

async def complete_challenge(challenge_id: int, winner_id: int) -> bool:
    """
    Finaliza un desafío MATCHED / IN_PROGRESS.
    """

    async with async_session() as session:
        challenge = await ChallengesCRUD.get(session, challenge_id)

        if not challenge:
            return False

        if challenge.status not in (
            ChallengeStatus.MATCHED,
            ChallengeStatus.IN_PROGRESS,
        ):
            return False

        if winner_id not in (challenge.challenger_id, challenge.opponent_id):
            return False

        loser_id = (
            challenge.opponent_id
            if winner_id == challenge.challenger_id
            else challenge.challenger_id
        )

        success = await transfer_prize_to_winner(
            winner_id=winner_id,
            loser_id=loser_id,
            prize_amount=challenge.prize_amount,
            bet_amount=challenge.bet_amount,
            session=session,
        )

        if not success:
            return False

        await ChallengesCRUD.update(
            session=session,
            challenge_id=challenge_id,
            winner_id=winner_id,
            status=ChallengeStatus.COMPLETED,
            completed_at=now_utc(),
        )

        await session.commit()
        return True


# ============================================================
# Funciones administrativas
# ============================================================

async def admin_force_cancel_challenge(challenge_id: int) -> bool:
    async with async_session() as session:
        challenge = await ChallengesCRUD.get(session, challenge_id)

        if not challenge:
            return False

        if challenge.status in (
            ChallengeStatus.OPEN,
            ChallengeStatus.MATCHED,
        ):
            await unfreeze_balance(
                challenge.challenger_id,
                challenge.bet_amount,
                session=session,
            )
            if challenge.opponent_id:
                await unfreeze_balance(
                    challenge.opponent_id,
                    challenge.bet_amount,
                    session=session,
                )

        await ChallengesCRUD.update(
            session=session,
            challenge_id=challenge_id,
            status=ChallengeStatus.CANCELLED,
        )

        await session.commit()
        return True


# ============================================================
# ADMIN — LISTAR RETOS
# ============================================================

async def admin_list_challenges(
    *,
    status: Optional[str] = None,
    limit: int = 50,
):
    async with async_session() as session:
        q = session.query(Challenge)

        if status:
            q = q.filter(Challenge.status == status)

        q = q.order_by(Challenge.created_at.desc()).limit(limit)
        return q.all()


# ============================================================
# ADMIN — GET RETO
# ============================================================

async def admin_get_challenge(challenge_id: int):
    async with async_session() as session:
        return await session.get(Challenge, challenge_id)


# ============================================================
# ADMIN — ASIGNAR GANADOR
# ============================================================

async def admin_assign_winner(challenge_id: int, winner_id: int) -> bool:
    return await complete_challenge(challenge_id, winner_id)
