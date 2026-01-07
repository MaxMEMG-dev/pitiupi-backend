# ============================================================
# database/services/channels_service.py — PITIUPI v5.0
# Servicio de gestión de canales de juegos
# HANDLERS → SERVICES → CRUD → MODELS
# ============================================================

import logging
from typing import Optional, List, Any, Dict, Tuple

from database.models.channels import GameChannel
from database.crud.channels import (
    get_all,
    get_by_id,
    get_by_game,
    create,
    update_single_field,
    update_fields,
    delete_channel,
    list_active,
    list_public,
    increment_stat,
)

from database.utils import now_utc

# NUEVO — creación real de canales vía Telethon
from database.telegram.telethon_client import create_telegram_channel, TELETHON_ENABLED

logger = logging.getLogger(__name__)

# ============================================================
# LISTAR / CONSULTAR
# ============================================================

async def admin_list_channels() -> List[GameChannel]:
    """
    Obtiene todos los canales de la base de datos.
    Retorna lista vacía si hay error o no hay canales.
    """
    try:
        channels = await get_all()
        logger.info(f"admin_list_channels: obtenidos {len(channels) if channels else 0} canales")
        return channels or []
    except Exception as e:
        logger.error(f"Error en admin_list_channels: {e}")
        return []


async def admin_get_channel(channel_id: int) -> Optional[GameChannel]:
    """
    Obtiene un canal por su ID.
    Retorna None si no existe o hay error.
    """
    try:
        channel = await get_by_id(channel_id)
        if not channel:
            logger.warning(f"Canal {channel_id} no encontrado")
        return channel
    except Exception as e:
        logger.error(f"Error obteniendo canal {channel_id}: {e}")
        return None


async def find_channel_by_game(game_name: str) -> Optional[GameChannel]:
    """
    Busca un canal por nombre de juego (case-insensitive).
    """
    try:
        if not game_name:
            return None
        return await get_by_game(game_name.upper().strip())
    except Exception as e:
        logger.error(f"Error buscando canal por juego '{game_name}': {e}")
        return None


async def list_public_channels() -> List[GameChannel]:
    """
    Lista todos los canales públicos.
    """
    try:
        return await list_public() or []
    except Exception as e:
        logger.error(f"Error listando canales públicos: {e}")
        return []


async def list_active_channels() -> List[GameChannel]:
    """
    Lista todos los canales activos.
    """
    try:
        return await list_active() or []
    except Exception as e:
        logger.error(f"Error listando canales activos: {e}")
        return []


# ============================================================
# CREAR CANAL AUTOMÁTICO (TELEGRAM + DB)
# ============================================================

async def admin_create_channel(
    game_name: str,
    *,
    description: Optional[str] = None,
    display_name: Optional[str] = None,
    modes: Optional[List[str]] = None,
    team_sizes: Optional[List[int]] = None,
    supports_public: bool = True,
    supports_private: bool = True,
    requires_match_link: bool = True,
    photo_path: Optional[str] = None,
) -> Tuple[Optional[GameChannel], str]:
    """
    Creación completa:
    1) Valida datos y duplicados
    2) Crea canal físico en Telegram
    3) Inserta registro en DB
    
    Retorna: (canal_creado, mensaje_error_o_exito)
    """
    
    logger.info(f"Iniciando creación de canal para juego: {game_name}")

    # -------------------------------
    # (0) Validar nombre
    # -------------------------------
    if not game_name or len(game_name.strip()) < 2:
        error_msg = "❌ Nombre de juego inválido. Mínimo 2 caracteres."
        logger.warning(error_msg)
        return None, error_msg

    game_name = game_name.strip().upper()
    display_name = display_name or f"PITIUPI - {game_name}"
    description = description or f"Canal oficial de retos PITIUPI para {game_name}."

    logger.debug(f"Parámetros procesados: juego={game_name}, display={display_name}")

    # -------------------------------
    # (1) Evitar duplicados
    # -------------------------------
    try:
        existing = await find_channel_by_game(game_name)
        if existing:
            error_msg = f"⚠️ Ya existe un canal registrado para el juego *{game_name}*."
            logger.warning(error_msg)
            return None, error_msg
    except Exception as e:
        error_msg = f"❌ Error verificando duplicados: {e}"
        logger.error(error_msg)
        return None, error_msg

    # -------------------------------
    # (1.5) Verificar si Telethon está habilitado
    # -------------------------------
    if not TELETHON_ENABLED:
        error_msg = "❌ Telethon no está configurado en producción. No se puede crear canal físico en Telegram."
        logger.error(error_msg)
        return None, error_msg

    # -------------------------------
    # (2) Crear canal físico con Telethon
    # -------------------------------
    telegram_chat_id = None
    telegram_chat_username = None
    telegram_chat_title = None
    
    try:
        logger.info(f"Creando canal físico en Telegram para {game_name}")
        tg_info = await create_telegram_channel(
            game_name=game_name,
            description=description,
            photo_path=photo_path
        )
        
        if not tg_info:
            error_msg = "❌ Telethon no retornó información del canal creado."
            logger.error(error_msg)
            return None, error_msg
            
        telegram_chat_id = str(tg_info.get("chat_id", ""))
        telegram_chat_username = tg_info.get("username")
        telegram_chat_title = tg_info.get("title") or display_name
        
        if not telegram_chat_id or telegram_chat_id == "0":
            error_msg = "❌ Chat ID inválido retornado por Telethon."
            logger.error(error_msg)
            return None, error_msg
            
        logger.info(f"Canal Telegram creado: ID={telegram_chat_id}, Title={telegram_chat_title}")
        
    except Exception as e:
        error_msg = f"❌ Error creando canal en Telegram: {e}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg

    # -------------------------------
    # (3) Armar configuración JSON
    # -------------------------------
    settings: Dict[str, Any] = {
        "description": description,
        "modes": modes or ["1v1"],
        "team_sizes": team_sizes or [],
        "supports_public": supports_public,
        "supports_private": supports_private,
        "requires_match_link": requires_match_link,
        "created_via": "admin_create_channel",
    }

    # -------------------------------
    # (4) Registrar canal en DB
    # -------------------------------
    try:
        channel = await create(
            game_name=game_name,
            display_name=display_name,
            telegram_chat_id=telegram_chat_id,
            telegram_chat_username=telegram_chat_username,
            telegram_chat_title=telegram_chat_title,
            is_active=True,
            is_public=True,
            auto_publish=True,
            challenge_count=0,
            tournament_count=0,
            settings=settings,
        )

        if not channel:
            error_msg = "❌ Error creando canal en la base de datos (retornó None)."
            logger.error(error_msg)
            return None, error_msg
            
        logger.info(f"Canal creado exitosamente en DB: ID={channel.id}, Game={channel.game_name}")
        return channel, "✅ Canal creado exitosamente en Telegram y base de datos."
        
    except Exception as e:
        error_msg = f"❌ Error registrando canal en base de datos: {e}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg


# ============================================================
# ACTUALIZACIONES
# ============================================================

async def admin_update_channel_field(channel_id: int, field: str, value: Any) -> bool:
    """
    Actualiza un solo campo de un canal.
    Retorna True si se actualizó correctamente.
    """
    try:
        if field not in ["game_name", "display_name", "telegram_chat_id", 
                        "telegram_chat_username", "telegram_chat_title",
                        "is_active", "is_public", "auto_publish", "settings"]:
            logger.warning(f"Campo '{field}' no permitido para actualización")
            return False
            
        success = await update_single_field(channel_id, field, value)
        if success:
            logger.info(f"Campo '{field}' actualizado para canal {channel_id}")
        else:
            logger.warning(f"No se pudo actualizar campo '{field}' para canal {channel_id}")
        return success
    except Exception as e:
        logger.error(f"Error actualizando campo '{field}' para canal {channel_id}: {e}")
        return False


async def admin_update_channel_fields(channel_id: int, **fields) -> bool:
    """
    Actualiza múltiples campos de un canal.
    Retorna True si se actualizó correctamente.
    """
    try:
        if not fields:
            logger.warning(f"No hay campos para actualizar para canal {channel_id}")
            return False
            
        # Filtrar campos permitidos
        allowed_fields = ["game_name", "display_name", "telegram_chat_id", 
                         "telegram_chat_username", "telegram_chat_title",
                         "is_active", "is_public", "auto_publish", "settings"]
        
        filtered_fields = {k: v for k, v in fields.items() if k in allowed_fields}
        
        if not filtered_fields:
            logger.warning(f"No hay campos válidos para actualizar para canal {channel_id}")
            return False
            
        success = await update_fields(channel_id, **filtered_fields)
        if success:
            logger.info(f"Campos {list(filtered_fields.keys())} actualizados para canal {channel_id}")
        return success
    except Exception as e:
        logger.error(f"Error actualizando campos para canal {channel_id}: {e}")
        return False


# ============================================================
# TOGGLES
# ============================================================

async def admin_toggle_channel_active(channel_id: int) -> bool:
    """
    Alterna el estado activo/inactivo de un canal.
    """
    try:
        channel = await admin_get_channel(channel_id)
        if not channel:
            logger.warning(f"No se encontró canal {channel_id} para toggle active")
            return False
            
        new_value = not channel.is_active
        success = await update_single_field(channel_id, "is_active", new_value)
        
        if success:
            status = "ACTIVADO" if new_value else "DESACTIVADO"
            logger.info(f"Canal {channel_id} {status} (is_active={new_value})")
        else:
            logger.warning(f"No se pudo alternar estado activo para canal {channel_id}")
            
        return success
    except Exception as e:
        logger.error(f"Error alternando estado activo para canal {channel_id}: {e}")
        return False


async def admin_toggle_channel_public(channel_id: int) -> bool:
    """
    Alterna el estado público/privado de un canal.
    """
    try:
        channel = await admin_get_channel(channel_id)
        if not channel:
            logger.warning(f"No se encontró canal {channel_id} para toggle public")
            return False
            
        new_value = not channel.is_public
        success = await update_single_field(channel_id, "is_public", new_value)
        
        if success:
            status = "PÚBLICO" if new_value else "PRIVADO"
            logger.info(f"Canal {channel_id} marcado como {status} (is_public={new_value})")
        else:
            logger.warning(f"No se pudo alternar visibilidad para canal {channel_id}")
            
        return success
    except Exception as e:
        logger.error(f"Error alternando visibilidad para canal {channel_id}: {e}")
        return False


async def admin_toggle_auto_publish(channel_id: int) -> bool:
    """
    Alterna el estado de auto-publicación de un canal.
    """
    try:
        channel = await admin_get_channel(channel_id)
        if not channel:
            logger.warning(f"No se encontró canal {channel_id} para toggle auto_publish")
            return False
            
        new_value = not channel.auto_publish
        success = await update_single_field(channel_id, "auto_publish", new_value)
        
        if success:
            status = "ACTIVADA" if new_value else "DESACTIVADA"
            logger.info(f"Auto-publicación {status} para canal {channel_id} (auto_publish={new_value})")
        else:
            logger.warning(f"No se pudo alternar auto-publicación para canal {channel_id}")
            
        return success
    except Exception as e:
        logger.error(f"Error alternando auto-publicación para canal {channel_id}: {e}")
        return False


# ============================================================
# ESTADÍSTICAS
# ============================================================

async def increment_challenge_count(channel_id: int) -> bool:
    """
    Incrementa el contador de retos publicados en un canal.
    Retorna True si se actualizó correctamente.
    """
    try:
        logger.debug(f"Incrementando challenge_count para canal {channel_id}")
        return await increment_stat(channel_id, "challenge_count")
    except Exception as e:
        logger.error(f"Error incrementando challenge_count para canal {channel_id}: {e}")
        return False


async def increment_tournament_count(channel_id: int) -> bool:
    """
    Incrementa el contador de torneos publicados en un canal.
    Retorna True si se actualizó correctamente.
    """
    try:
        logger.debug(f"Incrementando tournament_count para canal {channel_id}")
        return await increment_stat(channel_id, "tournament_count")
    except Exception as e:
        logger.error(f"Error incrementando tournament_count para canal {channel_id}: {e}")
        return False


async def increment_channel_challenge_count(channel_id: int) -> bool:
    """
    Alias para increment_challenge_count (mantener compatibilidad).
    """
    return await increment_challenge_count(channel_id)


# ============================================================
# ELIMINAR
# ============================================================

async def admin_delete_channel(channel_id: int) -> bool:
    """
    Elimina un canal de la base de datos.
    Retorna True si se eliminó correctamente.
    """
    try:
        logger.warning(f"Intentando eliminar canal {channel_id}")
        success = await delete_channel(channel_id)
        
        if success:
            logger.warning(f"Canal {channel_id} eliminado de la base de datos")
        else:
            logger.warning(f"No se pudo eliminar canal {channel_id}")
            
        return success
    except Exception as e:
        logger.error(f"Error eliminando canal {channel_id}: {e}")
        return False


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

async def get_channel_by_telegram_id(telegram_chat_id: str) -> Optional[GameChannel]:
    """
    Busca un canal por su Telegram Chat ID.
    """
    try:
        channels = await admin_list_channels()
        for channel in channels:
            if str(channel.telegram_chat_id) == str(telegram_chat_id):
                return channel
        return None
    except Exception as e:
        logger.error(f"Error buscando canal por Telegram ID {telegram_chat_id}: {e}")
        return None


async def get_active_public_channels() -> List[GameChannel]:
    """
    Obtiene todos los canales que están activos Y públicos.
    """
    try:
        all_channels = await admin_list_channels()
        return [c for c in all_channels if c.is_active and c.is_public]
    except Exception as e:
        logger.error(f"Error obteniendo canales activos y públicos: {e}")
        return []


async def update_channel_last_published(channel_id: int) -> bool:
    """
    Actualiza la fecha del último publish de un canal.
    """
    from datetime import datetime
    try:
        from database.crud.channels import update_single_field
        now = now_utc()
        return await update_single_field(channel_id, "last_published_at", now)
    except Exception as e:
        logger.error(f"Error actualizando last_published_at para canal {channel_id}: {e}")
        return False
