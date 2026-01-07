# ============================================================
# database/services/challenge_participants_service.py — PITIUPI v5.0
# Servicio de participantes por reto (equipos Azul/Rojo)
# Arquitectura: Handlers → Services → CRUD/DB
#
# Responsabilidad:
# - Agregar/quitar jugadores a un reto por equipo
# - Validar cupos (según game_mode: 1v1, 4v4, 10v10, etc.)
# - Evitar duplicados
# - (Opcional) congelar/liberar balance por jugador al unirse/salir
# - (Opcional) marcar reto como MATCHED cuando ambos equipos estén completos
#
# NOTA:
# - Permisos “público/privado” (quién puede unirse) deben validarse en handlers.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Literal

from sqlalchemy import select, func, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import async_session
from database.utils import now_utc

# Modelos
from database.models.user import User, UserStatus
from database.models.challenges import Challenge, ChallengeStatus
from database.models.challenge_participants import ChallengeParticipant  # <-- debes tener este modelo

# Servicios financieros (opcionales en join/leave)
from database.services.users_service import (
    get_user_balance,
    freeze_balance,
    unfreeze_balance,
)

Team = Literal["blue", "red"]


# ============================================================
# Resultado tipado para UX/UI (handlers)
# ============================================================

@dataclass
class JoinResult:
    ok: bool
    message: str
    challenge_id: int
    team: Optional[Team] = None
    team_size: Optional[int] = None
    blue_count: Optional[int] = None
    red_count: Optional[int] = None
    is_full: Optional[bool] = None


# ============================================================
# Helpers internos
# ============================================================

def _parse_team_size(game_mode: str) -> int:
    """
    Obtiene tamaño de equipo desde game_mode.
    Ejemplos válidos:
      - "1v1" -> 1
      - "4v4" -> 4
      - "10v10" -> 10
    Si no se puede parsear, cae a 1.
    """
    if not game_mode:
        return 1

    raw = str(game_mode).lower().strip()

    # soporta formatos tipo "4v4", "4 vs 4", "4v4 ranked" (toma primera ocurrencia)
    raw = raw.replace(" ", "")
    if "vs" in raw:
        raw = raw.replace("vs", "v")

    if "v" not in raw:
        return 1

    left, _, right = raw.partition("v")
    try:
        a = int(left)
        # right podría venir con sufijos (ej: "4ranked") -> toma prefijo numérico
        digits = ""
        for ch in right:
            if ch.isdigit():
                digits += ch
            else:
                break
        b = int(digits) if digits else a
        # si no es simétrico, usamos el mínimo para cupos por equipo
        return max(1, min(a, b))
    except Exception:
        return 1


def _validate_team(team: str) -> Team:
    t = str(team).lower().strip()
    if t in ("blue", "azul"):
        return "blue"
    if t in ("red", "rojo"):
        return "red"
    raise ValueError("Equipo inválido (usa 'blue'/'red' o 'Azul'/'Rojo').")


async def _get_challenge(session: AsyncSession, challenge_id: int) -> Optional[Challenge]:
    res = await session.execute(select(Challenge).where(Challenge.id == challenge_id))
    return res.scalar_one_or_none()


async def _team_counts(session: AsyncSession, challenge_id: int) -> Tuple[int, int]:
    q = (
        select(ChallengeParticipant.team, func.count())
        .where(ChallengeParticipant.challenge_id == challenge_id)
        .group_by(ChallengeParticipant.team)
    )
    rows = (await session.execute(q)).all()

    blue = 0
    red = 0
    for team, count in rows:
        if team == "blue":
            blue = int(count or 0)
        elif team == "red":
            red = int(count or 0)
    return blue, red


async def _user_participant(session: AsyncSession, challenge_id: int, user_id: int) -> Optional[ChallengeParticipant]:
    q = select(ChallengeParticipant).where(
        ChallengeParticipant.challenge_id == challenge_id,
        ChallengeParticipant.user_id == user_id,
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()


def _is_joinable_status(status: str) -> bool:
    # Permitimos unirse mientras el reto está abierto o emparejado pero no lleno.
    return status in (ChallengeStatus.OPEN, ChallengeStatus.MATCHED)


# ============================================================
# API pública del servicio
# ============================================================

async def get_roster(challenge_id: int) -> Dict[str, List[int]]:
    """
    Retorna los user_id por equipo:
      {"blue": [..], "red": [..]}
    """
    async with async_session() as session:
        q = select(ChallengeParticipant.user_id, ChallengeParticipant.team).where(
            ChallengeParticipant.challenge_id == challenge_id
        )
        rows = (await session.execute(q)).all()

        roster = {"blue": [], "red": []}
        for user_id, team in rows:
            if team == "blue":
                roster["blue"].append(int(user_id))
            elif team == "red":
                roster["red"].append(int(user_id))
        return roster


async def get_user_team(challenge_id: int, user_id: int) -> Optional[Team]:
    async with async_session() as session:
        p = await _user_participant(session, challenge_id, user_id)
        return p.team if p else None


async def count_members(challenge_id: int) -> Tuple[int, int]:
    async with async_session() as session:
        return await _team_counts(session, challenge_id)


async def is_full(challenge_id: int) -> bool:
    async with async_session() as session:
        ch = await _get_challenge(session, challenge_id)
        if not ch:
            return False
        team_size = _parse_team_size(ch.game_mode)
        blue, red = await _team_counts(session, challenge_id)
        return blue >= team_size and red >= team_size


async def pick_auto_team(challenge_id: int) -> Optional[Team]:
    """
    Escoge equipo automático: el que tenga menos jugadores.
    Retorna None si ya está lleno (ambos).
    """
    async with async_session() as session:
        ch = await _get_challenge(session, challenge_id)
        if not ch:
            return None
        team_size = _parse_team_size(ch.game_mode)
        blue, red = await _team_counts(session, challenge_id)

        if blue >= team_size and red >= team_size:
            return None
        if blue < red:
            return "blue"
        if red < blue:
            return "red"
        # empate -> blue por defecto
        return "blue"


async def ensure_challenger_in_team(
    *,
    challenge_id: int,
    challenger_user_id: int,
    team: Team = "blue",
) -> bool:
    """
    Asegura que el creador esté registrado como participante del reto.
    Útil en retos por equipos para que el creador quede en Azul por defecto.
    """
    async with async_session() as session:
        existing = await _user_participant(session, challenge_id, challenger_user_id)
        if existing:
            return True

        session.add(
            ChallengeParticipant(
                challenge_id=challenge_id,
                user_id=challenger_user_id,
                team=team,
            )
        )
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return True
        except Exception:
            await session.rollback()
            return False


async def join_team(
    *,
    challenge_id: int,
    user_id: int,
    team: str,
    freeze_on_join: bool = False,
    auto_match_when_full: bool = True,
) -> JoinResult:
    """
    Une a un usuario a un equipo (blue/red) en un reto.

    Validaciones:
    - reto existe
    - status joinable (OPEN/MATCHED)
    - usuario existe/activo
    - usuario no duplicado
    - cupo disponible
    - (opcional) freeze balance por jugador

    auto_match_when_full:
    - si tras el join ambos equipos quedan completos, actualiza status a MATCHED y started_at.
    """
    try:
        team_norm = _validate_team(team)
    except Exception as e:
        return JoinResult(False, f"❌ {e}", challenge_id)

    async with async_session() as session:
        ch = await _get_challenge(session, challenge_id)
        if not ch:
            return JoinResult(False, "❌ El reto no existe.", challenge_id)

        if not _is_joinable_status(ch.status):
            return JoinResult(False, "❌ Este reto no está disponible para unirse.", challenge_id)

        team_size = _parse_team_size(ch.game_mode)

        # validar usuario
        user = await session.get(User, user_id)
        if not user or user.status != UserStatus.ACTIVE:
            return JoinResult(False, "❌ Usuario no activo o no válido.", challenge_id)

        # evitar duplicados
        existing = await _user_participant(session, challenge_id, user_id)
        if existing:
            return JoinResult(
                True,
                f"ℹ️ Ya estás en el reto en el equipo {existing.team.upper()}.",
                challenge_id,
                team=existing.team,
                team_size=team_size,
            )

        blue, red = await _team_counts(session, challenge_id)
        if team_norm == "blue" and blue >= team_size:
            return JoinResult(False, "❌ Equipo AZUL lleno.", challenge_id, team="blue", team_size=team_size, blue_count=blue, red_count=red)
        if team_norm == "red" and red >= team_size:
            return JoinResult(False, "❌ Equipo ROJO lleno.", challenge_id, team="red", team_size=team_size, blue_count=blue, red_count=red)

        # (opcional) freeze balance por jugador al unirse
        if freeze_on_join:
            # Nota: bet_amount se interpreta como "apuesta por jugador"
            amount = ch.bet_amount
            bal = await get_user_balance(user_id)
            if bal < amount:
                return JoinResult(False, f"❌ Saldo insuficiente para unirte. Necesitas {amount}.", challenge_id)

            # congelar dentro de la misma transacción/session
            await freeze_balance(user_id, amount, session=session)

        # insertar participante
        session.add(
            ChallengeParticipant(
                challenge_id=challenge_id,
                user_id=user_id,
                team=team_norm,
            )
        )

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # alguien pudo haberse unido al mismo tiempo
            return JoinResult(False, "❌ No se pudo unir (duplicado/competencia). Intenta de nuevo.", challenge_id)
        except Exception as e:
            await session.rollback()
            return JoinResult(False, f"❌ Error uniendo al reto: {str(e)[:160]}", challenge_id)

        # recomputar counts
        async with async_session() as session2:
            blue2, red2 = await _team_counts(session2, challenge_id)
            full_now = (blue2 >= team_size and red2 >= team_size)

            # auto-matching
            if auto_match_when_full and full_now and ch.status == ChallengeStatus.OPEN:
                try:
                    await session2.execute(
                        update(Challenge)
                        .where(Challenge.id == challenge_id)
                        .values(
                            status=ChallengeStatus.MATCHED,
                            started_at=now_utc(),
                        )
                    )
                    await session2.commit()
                except Exception:
                    await session2.rollback()

            return JoinResult(
                True,
                f"✅ Te uniste al equipo {'AZUL' if team_norm=='blue' else 'ROJO'}.",
                challenge_id,
                team=team_norm,
                team_size=team_size,
                blue_count=blue2,
                red_count=red2,
                is_full=full_now,
            )


async def leave_challenge(
    *,
    challenge_id: int,
    user_id: int,
    unfreeze_on_leave: bool = False,
) -> JoinResult:
    """
    Saca al usuario del reto (si estaba).
    (Opcional) libera el balance congelado del jugador.
    """
    async with async_session() as session:
        ch = await _get_challenge(session, challenge_id)
        if not ch:
            return JoinResult(False, "❌ El reto no existe.", challenge_id)

        p = await _user_participant(session, challenge_id, user_id)
        if not p:
            return JoinResult(False, "ℹ️ No estabas dentro de este reto.", challenge_id)

        # Opcional: liberar saldo congelado al salir (si tu UX lo permite)
        if unfreeze_on_leave:
            try:
                await unfreeze_balance(user_id, ch.bet_amount, session=session)
            except Exception:
                # si falla, no removemos para evitar estado inconsistente
                await session.rollback()
                return JoinResult(False, "❌ No se pudo liberar tu saldo, no se removió tu participación.", challenge_id)

        await session.execute(
            delete(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.user_id == user_id,
            )
        )

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            return JoinResult(False, f"❌ Error saliendo del reto: {str(e)[:160]}", challenge_id)

        # counts actuales
        async with async_session() as session2:
            team_size = _parse_team_size(ch.game_mode)
            blue, red = await _team_counts(session2, challenge_id)
            return JoinResult(
                True,
                "✅ Saliste del reto.",
                challenge_id,
                team_size=team_size,
                blue_count=blue,
                red_count=red,
                is_full=(blue >= team_size and red >= team_size),
            )


async def switch_team(
    *,
    challenge_id: int,
    user_id: int,
    new_team: str,
) -> JoinResult:
    """
    Cambia al usuario de equipo (blue<->red) si hay cupo.
    No toca balances.
    """
    try:
        new_team_norm = _validate_team(new_team)
    except Exception as e:
        return JoinResult(False, f"❌ {e}", challenge_id)

    async with async_session() as session:
        ch = await _get_challenge(session, challenge_id)
        if not ch:
            return JoinResult(False, "❌ El reto no existe.", challenge_id)

        if not _is_joinable_status(ch.status):
            return JoinResult(False, "❌ No puedes cambiar de equipo en este estado del reto.", challenge_id)

        p = await _user_participant(session, challenge_id, user_id)
        if not p:
            return JoinResult(False, "❌ No estás unido al reto.", challenge_id)

        if p.team == new_team_norm:
            return JoinResult(True, "ℹ️ Ya estás en ese equipo.", challenge_id, team=p.team)

        team_size = _parse_team_size(ch.game_mode)
        blue, red = await _team_counts(session, challenge_id)

        if new_team_norm == "blue" and blue >= team_size:
            return JoinResult(False, "❌ Equipo AZUL lleno.", challenge_id, team="blue", team_size=team_size, blue_count=blue, red_count=red)
        if new_team_norm == "red" and red >= team_size:
            return JoinResult(False, "❌ Equipo ROJO lleno.", challenge_id, team="red", team_size=team_size, blue_count=blue, red_count=red)

        await session.execute(
            update(ChallengeParticipant)
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.user_id == user_id,
            )
            .values(team=new_team_norm)
        )

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            return JoinResult(False, f"❌ Error cambiando de equipo: {str(e)[:160]}", challenge_id)

        blue2, red2 = await _team_counts(session, challenge_id)
        full_now = (blue2 >= team_size and red2 >= team_size)

        return JoinResult(
            True,
            f"✅ Cambiaste al equipo {'AZUL' if new_team_norm=='blue' else 'ROJO'}.",
            challenge_id,
            team=new_team_norm,
            team_size=team_size,
            blue_count=blue2,
            red_count=red2,
            is_full=full_now,
        )
