# ============================================================
# services/tournaments_service.py — PITIUPI v5.0
# Lógica del negocio para torneos (ASYNC)
# ============================================================

from decimal import Decimal
from typing import Optional, Dict, Any, List

from database.session import async_db_session
from database.utils import now_utc

# ------------------ CRUD CORRECTOS --------------------------

from database.crud.user_crud import (
    get_user_by_id,
    lock_balance,
    unlock_balance,
    apply_win,
)

from database.crud.tournaments_crud import (
    create_tournament_record,
    get_tournament,
    update_tournament_status,
    add_participant,
    list_participants,
    set_winner,
    increment_player_count,
)

from database.crud.transaction_crud import add_transaction
from database.crud.system_config_crud import get_config_number


# ============================================================
# Crear torneo
# ============================================================

async def create_tournament(
    name: str,
    game_name: str,
    game_mode: str,
    max_players: int,
    entry_fee: Decimal,
    prize_structure: List[Dict[str, Any]],
    creator_id: int,
    description: Optional[str] = None,
    registration_opens_at=None,
    registration_closes_at=None,
    starts_at=None,
) -> Dict[str, Any]:

    rake_percentage = await get_config_number("rake_tournament")
    rake_percentage = Decimal(str(rake_percentage or 0))

    if max_players < 2:
        raise ValueError("El torneo debe permitir al menos 2 jugadores")

    if entry_fee <= 0:
        raise ValueError("La entrada debe ser mayor a 0")

    tournament = await create_tournament_record(
        name=name,
        description=description,
        game_name=game_name,
        game_mode=game_mode,
        max_players=max_players,
        entry_fee=entry_fee,
        rake_percentage=rake_percentage,
        prize_structure=prize_structure,
        created_by=creator_id,
        registration_opens_at=registration_opens_at,
        registration_closes_at=registration_closes_at,
        starts_at=starts_at,
    )

    return tournament


# ============================================================
# Unirse a torneo
# ============================================================

async def join_tournament(tournament_uuid: str, user_id: int) -> Dict[str, Any]:

    tournament = await get_tournament(tournament_uuid)
    if not tournament:
        raise ValueError("Torneo no encontrado")

    if tournament.status not in ("open", "draft"):
        raise ValueError("El torneo ya no acepta jugadores")

    if tournament.current_players >= tournament.max_players:
        raise ValueError("El torneo está lleno")

    user = await get_user_by_id(user_id)
    if user.balance_available < tournament.entry_fee:
        raise ValueError("Saldo insuficiente")

    # Bloquear balance
    await lock_balance(user_id, tournament.entry_fee)

    # Registrar participante
    await add_participant(tournament_uuid, user_id)

    # Actualizar contador
    await increment_player_count(tournament_uuid)

    # Si está completo → cambiar a "full"
    if tournament.current_players + 1 >= tournament.max_players:
        await update_tournament_status(tournament_uuid, "full")

    return {"joined": True}


# ============================================================
# Iniciar torneo
# ============================================================

async def start_tournament(tournament_uuid: str) -> Dict[str, Any]:

    tournament = await get_tournament(tournament_uuid)
    if not tournament:
        raise ValueError("Torneo no encontrado")

    if tournament.status not in ("open", "full"):
        raise ValueError("El torneo no está listo para iniciar")

    await update_tournament_status(tournament_uuid, "started")

    return {"started": True}


# ============================================================
# Completar torneo y pagar premios
# ============================================================

async def complete_tournament(
    tournament_uuid: str,
    winners: List[int],
) -> Dict[str, Any]:

    tournament = await get_tournament(tournament_uuid)
    if not tournament:
        raise ValueError("Torneo no encontrado")

    if tournament.status not in ("started", "full"):
        raise ValueError("El torneo no está en curso")

    participants = await list_participants(tournament_uuid)
    if not participants:
        raise ValueError("No hay jugadores registrados")

    entry_fee = Decimal(str(tournament.entry_fee))
    rake = Decimal(str(tournament.rake_percentage))

    total_pot = entry_fee * Decimal(len(participants))
    rake_amount = total_pot * rake
    prize_pool = total_pot - rake_amount

    prize_structure = tournament.prize_structure

    results = []

    # Pagar premios según estructura
    for pos, winner_id in enumerate(winners, start=1):
        cfg = next((p for p in prize_structure if p["position"] == pos), None)
        if not cfg:
            continue

        percentage = Decimal(str(cfg["percentage"]))
        prize = prize_pool * percentage

        await apply_win(winner_id, prize)

        await add_transaction(
            user_id=winner_id,
            type="win_tournament",
            amount=prize,
            balance_before=None,
            balance_after=None,
            reference_type="tournament",
            reference_id=tournament_uuid,
        )

        results.append({
            "position": pos,
            "user_id": winner_id,
            "prize": float(prize)
        })

    await update_tournament_status(tournament_uuid, "completed")

    # Registrar campeón
    if winners:
        await set_winner(tournament_uuid, winners[0])

    return {
        "status": "completed",
        "results": results,
        "total_pot": float(total_pot),
        "prize_pool": float(prize_pool),
    }


# ============================================================
# Cancelar torneo (no iniciado)
# ============================================================

async def cancel_tournament(tournament_uuid: str) -> Dict[str, Any]:

    tournament = await get_tournament(tournament_uuid)
    if not tournament:
        raise ValueError("Torneo no encontrado")

    if tournament.status not in ("draft", "open"):
        raise ValueError("El torneo no puede cancelarse")

    participants = await list_participants(tournament_uuid)

    # Reembolsar
    for user_id in participants:
        await unlock_balance(user_id, tournament.entry_fee)

    await update_tournament_status(tournament_uuid, "canceled")

    return {"canceled": True}


# ============================================================
# ADMIN: Listado paginado de torneos
# ============================================================

async def admin_list_tournaments(status: str, page: int, page_size: int = 10):
    offset = (page - 1) * page_size

    tournaments = await list_tournaments_paginated(
        status=status,
        limit=page_size,
        offset=offset,
    )

    total = await count_tournaments(status)
    total_pages = max(1, (total + page_size - 1) // page_size)

    return tournaments, total_pages


# ============================================================
# ADMIN: Obtener torneo por ID
# ============================================================

async def admin_get_tournament(tournament_id: int):
    return await get_tournament(tournament_id)


# ============================================================
# ADMIN: Forzar inicio
# ============================================================

async def admin_force_start_tournament(tournament_id: int):
    t = await get_tournament(tournament_id)
    if not t:
        return False, "Torneo no encontrado"

    if t.status not in ("open", "full"):
        return False, "Este torneo no puede iniciarse"

    await update_tournament_status(tournament_id, "started")
    return True, "Torneo iniciado"


# ============================================================
# ADMIN: Forzar finalización
# ============================================================

async def admin_force_finish_tournament(tournament_id: int):
    t = await get_tournament(tournament_id)
    if not t:
        return False, "Torneo no encontrado"

    if t.status not in ("started", "full"):
        return False, "El torneo no está en curso"

    await update_tournament_status(tournament_id, "finished")
    return True, "Torneo finalizado"


# ============================================================
# ADMIN: Asignar ganador manual
# ============================================================

async def admin_assign_winner_tournament(tournament_id: int, winner_id: int | None = None):
    t = await get_tournament(tournament_id)
    if not t:
        return False, "Torneo no encontrado"

    participants = await list_participants(tournament_id)
    if not participants:
        return False, "No hay participantes"

    # Si admin no envía ganador → tomar primer jugador
    if winner_id is None:
        winner_id = participants[0]

    await set_winner(tournament_id, winner_id)
    return True, "Ganador asignado"


# ============================================================
# ADMIN: Agregar participante manual
# ============================================================

async def admin_add_participant(tournament_id: int, user_id: int):
    t = await get_tournament(tournament_id)
    if not t:
        return False, "Torneo no encontrado"

    if t.status not in ("draft", "open"):
        return False, "Este torneo no permite agregar jugadores"

    participants = await list_participants(tournament_id)
    if user_id in participants:
        return False, "El jugador ya está inscrito"

    await add_participant(tournament_id, user_id)
    return True, "Jugador agregado"


# ============================================================
# ADMIN: Remover participante manual
# ============================================================

async def admin_remove_participant(tournament_id: int, user_id: int):
    t = await get_tournament(tournament_id)
    if not t:
        return False, "Torneo no encontrado"

    participants = await list_participants(tournament_id)
    if user_id not in participants:
        return False, "El jugador no pertenece al torneo"

    await remove_participant(tournament_id, user_id)
    return True, "Jugador removido"
