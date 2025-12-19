# ============================================================
# users_api.py — Gestión de usuarios
# PITIUPI v6.0 — 100% V6-Compliant
# ============================================================

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator, Field
from typing import Optional
import logging

from database.session import get_db
from database.crud import user_crud
from database.models.user import User

router = APIRouter(tags=["users"])
logger = logging.getLogger(__name__)


# ============================================================
# MODELOS PYDANTIC
# ============================================================

class UserRegister(BaseModel):
    """
    V6: Request para registrar o actualizar usuario
    
    Attributes:
        telegram_id: ID de Telegram del usuario (único)
        first_name: Nombre del usuario
        last_name: Apellido (opcional)
        email: Email (requerido para Nuvei)
        phone: Teléfono (requerido para Nuvei)
        country: País (requerido para Nuvei)
        city: Ciudad (requerido para Nuvei)
        document_number: Cédula/RUC (requerido para Nuvei Ecuador)
    
    Note:
        - Strings vacíos se convierten a None
        - UPSERT: actualiza si existe, crea si no existe
        - NO toca balances (solo metadata de usuario)
    """
    telegram_id: int = Field(..., gt=0, description="Telegram ID del usuario")
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, max_length=10)
    city: Optional[str] = Field(None, max_length=100)
    document_number: Optional[str] = Field(None, max_length=50)

    @validator("*", pre=True)
    def empty_to_none(cls, v):
        """
        V6: Convierte strings vacíos a None
        
        Evita insertar "" en PostgreSQL que puede causar problemas
        con constraints y validaciones.
        """
        if v == "" or v is None:
            return None
        return v


class UserResponse(BaseModel):
    """
    V6: Response de usuario (solo lectura)
    
    Note:
        - Balance es READ-ONLY
        - NO se puede mutar balance desde API
        - Para cambiar balance: usar payments o withdrawals
    """
    id: int
    telegram_id: int
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    country: Optional[str]
    city: Optional[str]
    document_number: Optional[str]
    balance_available: float
    balance_locked: float
    balance_total: float
    created_at: str
    updated_at: str


class UserRegisterResponse(BaseModel):
    """V6: Response de registro/actualización"""
    success: bool
    user: UserResponse


class UserGetResponse(BaseModel):
    """V6: Response de consulta de usuario"""
    success: bool
    user: UserResponse


class UserDeleteResponse(BaseModel):
    """V6: Response de eliminación de usuario"""
    success: bool
    deleted: int
    detail: Optional[str] = None


# ============================================================
# HELPERS
# ============================================================

def serialize_user(user: User) -> UserResponse:
    """
    V6: Serializa modelo User a dict para response
    
    Args:
        user: Instancia del modelo User
    
    Returns:
        UserResponse con todos los campos
    
    Note:
        - Evita exponer modelo SQLAlchemy directamente
        - Convierte Decimal a float para JSON
        - Formatea timestamps a ISO
    """
    return UserResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        first_name=user.telegram_first_name,
        last_name=user.telegram_last_name,
        email=user.email,
        phone=user.phone,
        country=user.country,
        city=user.city,
        document_number=user.document_number,
        balance_available=float(user.balance_available),
        balance_locked=float(user.balance_locked),
        balance_total=float(user.balance_total),
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


# ============================================================
# POST /users/register
# Registrar o actualizar usuario (UPSERT)
# ============================================================

@router.post("/register", response_model=UserRegisterResponse)
def register_user(
    data: UserRegister,
    session: Session = Depends(get_db)
):
    """
    V6: Registra o actualiza usuario (UPSERT)
    
    RESPONSABILIDADES V6:
    - Crear usuario si no existe
    - Actualizar campos NO nulos si ya existe
    - Preservar campos existentes si nuevos son None
    
    NO HACE:
    - ❌ Tocar balances
    - ❌ Crear transacciones
    - ❌ Lógica financiera
    - ❌ Commits manuales
    
    Args:
        data: UserRegister con telegram_id + campos opcionales
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        UserRegisterResponse con usuario creado/actualizado
    
    Raises:
        500: Error interno
    
    Note:
        - Idempotente (se puede llamar múltiples veces)
        - COALESCE: solo actualiza campos NO nulos
        - Balance inicial = 0.00 (si es usuario nuevo)
    """
    try:
        logger.info(f"📥 Registro/actualización usuario TelegramID={data.telegram_id}")

        # V6: Delegar a CRUD (UPSERT)
        user = user_crud.upsert_user(
            telegram_id=data.telegram_id,
            telegram_first_name=data.first_name,
            telegram_last_name=data.last_name,
            email=data.email,
            phone=data.phone,
            country=data.country,
            city=data.city,
            document_number=data.document_number,
            session=session
        )
        
        session.flush()
        
        logger.info(f"✅ Usuario registrado/actualizado: ID={user.id}")

        return UserRegisterResponse(
            success=True,
            user=serialize_user(user)
        )

    except Exception as e:
        logger.error(f"❌ Error registrando usuario: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error registrando usuario: {str(e)}"
        )


# ============================================================
# GET /users/{telegram_id}
# Obtener usuario con balances (READ-ONLY)
# ============================================================

@router.get("/{telegram_id}", response_model=UserGetResponse)
def get_user(
    telegram_id: int,
    session: Session = Depends(get_db)
):
    """
    V6: Obtiene usuario por Telegram ID
    
    RESPONSABILIDADES V6:
    - Solo lectura
    - Retorna balances actuales (READ-ONLY)
    
    NO HACE:
    - ❌ Tocar balances
    - ❌ Calcular balances (ya están en User)
    - ❌ Sumar transacciones (ledger es histórico)
    
    Args:
        telegram_id: Telegram ID del usuario
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        UserGetResponse con usuario y balances
    
    Raises:
        404: Usuario no encontrado
        500: Error interno
    
    Note:
        - Balance viene directo de User.balance_*
        - NO se calcula desde Transaction (ledger es solo histórico)
    """
    try:
        user = user_crud.get_user_by_telegram_id(telegram_id, session=session)

        if not user:
            logger.warning(f"⚠️ Usuario Telegram {telegram_id} no encontrado")
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado"
            )

        return UserGetResponse(
            success=True,
            user=serialize_user(user)
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error obteniendo usuario: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error interno consultando usuario: {str(e)}"
        )


# ============================================================
# GET /users/by_id/{user_id}
# Obtener usuario por ID interno (admin/internal)
# ============================================================

@router.get("/by_id/{user_id}", response_model=UserGetResponse)
def get_user_by_id(
    user_id: int,
    session: Session = Depends(get_db)
):
    """
    V6: Obtiene usuario por ID interno
    
    Args:
        user_id: ID interno del usuario
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        UserGetResponse con usuario y balances
    
    Raises:
        404: Usuario no encontrado
        500: Error interno
    
    Note:
        - Endpoint para uso interno/admin
        - Preferir usar telegram_id en apps públicas
    """
    try:
        user = user_crud.get_user_by_id(user_id, session=session)

        if not user:
            logger.warning(f"⚠️ Usuario ID {user_id} no encontrado")
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado"
            )

        return UserGetResponse(
            success=True,
            user=serialize_user(user)
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error obteniendo usuario: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error interno consultando usuario: {str(e)}"
        )


# ============================================================
# DELETE /users/{telegram_id}
# Eliminar usuario + dependencias (HARD DELETE)
# ============================================================

@router.delete("/{telegram_id}", response_model=UserDeleteResponse)
def delete_user(
    telegram_id: int,
    session: Session = Depends(get_db)
):
    """
    V6: Elimina usuario y todas sus dependencias (HARD DELETE)
    
    CASCADAS V6:
    1. PaymentIntents
    2. Transactions (ledger)
    3. WithdrawalRequests
    4. Challenges
    5. Tournaments
    6. Usuario
    
    NO HACE:
    - ❌ Devolver balance (hard delete, no refunds)
    - ❌ Validar balance > 0 (decisión de negocio)
    
    Args:
        telegram_id: Telegram ID del usuario a eliminar
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        UserDeleteResponse con confirmación
    
    Raises:
        404: Usuario no encontrado
        500: Error interno
    
    WARNING:
        - IRREVERSIBLE
        - Elimina TODO el historial financiero
        - Usar solo en dev/testing o GDPR requests
    """
    try:
        logger.warning(f"🗑 Eliminando usuario TelegramID={telegram_id}")

        # Buscar usuario
        user = user_crud.get_user_by_telegram_id(telegram_id, session=session)
        
        if not user:
            return UserDeleteResponse(
                success=False,
                deleted=telegram_id,
                detail="Usuario no existe"
            )

        # V6: Delegar a CRUD (maneja cascadas)
        deleted = user_crud.delete_user(user_id=user.id, session=session)
        
        if not deleted:
            raise HTTPException(
                status_code=500,
                detail="Error eliminando usuario (no se pudo completar)"
            )
        
        session.flush()
        
        logger.warning(f"✅ Usuario eliminado: TelegramID={telegram_id}")

        return UserDeleteResponse(
            success=True,
            deleted=telegram_id,
            detail="Usuario y dependencias eliminadas"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error eliminando usuario: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error eliminando usuario: {str(e)}"
        )


# ============================================================
# PATCH /users/{telegram_id}/profile
# Actualizar solo campos de perfil (sin tocar balance)
# ============================================================

@router.patch("/{telegram_id}/profile", response_model=UserRegisterResponse)
def update_user_profile(
    telegram_id: int,
    data: UserRegister,
    session: Session = Depends(get_db)
):
    """
    V6: Actualiza solo campos de perfil (sin crear usuario)
    
    DIFERENCIA con /register:
    - /register: crea usuario si no existe (UPSERT)
    - /profile: solo actualiza, error si no existe
    
    Args:
        telegram_id: Telegram ID del usuario
        data: UserRegister con campos a actualizar
        session: Session SQLAlchemy (inyectada)
    
    Returns:
        UserRegisterResponse con usuario actualizado
    
    Raises:
        404: Usuario no encontrado
        500: Error interno
    
    Note:
        - Solo campos NO nulos se actualizan
        - Campos existentes se preservan si nuevos son None
    """
    try:
        logger.info(f"📝 Actualizando perfil TelegramID={telegram_id}")

        # Verificar usuario existe
        user = user_crud.get_user_by_telegram_id(telegram_id, session=session)
        if not user:
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado. Use /register para crear."
            )

        # Actualizar campos
        user = user_crud.update_user_profile(
            user_id=user.id,
            telegram_first_name=data.first_name,
            telegram_last_name=data.last_name,
            email=data.email,
            phone=data.phone,
            country=data.country,
            city=data.city,
            document_number=data.document_number,
            session=session
        )
        
        session.flush()
        
        logger.info(f"✅ Perfil actualizado: ID={user.id}")

        return UserRegisterResponse(
            success=True,
            user=serialize_user(user)
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"❌ Error actualizando perfil: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error actualizando perfil: {str(e)}"
        )
