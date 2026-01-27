# ============================================================
# users_api.py — API de Lectura de Usuarios
# Permite al Bot sincronizar saldos desde la nube
# ============================================================

from fastapi import APIRouter, HTTPException
import logging
from database.session import db_session
from database.models.user import User

router = APIRouter(tags=["Users"])
logger = logging.getLogger(__name__)

@router.get("/{telegram_id}")
def get_user_info(telegram_id: str):
    """
    Devuelve la información del usuario para sincronizar con el bot.
    """
    logger.info(f"📞 Solicitud de usuario: {telegram_id}")
    
    with db_session() as session:
        try:
            user = session.query(User).filter(User.telegram_id == telegram_id).first()
            
            if not user:
                logger.warning(f"❌ Usuario no encontrado: {telegram_id}")
                raise HTTPException(status_code=404, detail="User not found")
            
            # Calcular saldos
            available = float(user.balance_available or 0.0)
            locked = float(user.balance_locked or 0.0)
            total = float(user.balance_total or 0.0)
            
            logger.info(f"✅ Usuario encontrado: {telegram_id} - Balance: ${total}")
            
            return {
                "status": "success",
                "user": {
                    "telegram_id": user.telegram_id,
                    "balance_available": available,
                    "balance_locked": locked,
                    "balance_total": total,
                    "total_deposits": float(user.total_deposits or 0.0),
                    "is_verified": user.is_verified,
                    "status": user.status,
                    "first_deposit_made": user.first_deposit_made or False
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error fetching user {telegram_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal Server Error")
