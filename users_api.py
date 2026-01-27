# ============================================================
# users_api.py — API de Lectura de Usuarios
# Permite al Bot sincronizar saldos desde la nube
# ============================================================

from fastapi import APIRouter, HTTPException
import logging
from database.session import SessionLocal
from database.models.user import User

router = APIRouter(tags=["Users"])
logger = logging.getLogger(__name__)

@router.get("/{telegram_id}")
def get_user_info(telegram_id: str):
    """
    Devuelve la información vital del usuario (saldo) 
    para sincronizar con el bot local.
    """
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.telegram_id == telegram_id).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Calcular saldo total real (Recharge + Withdrawable)
        recharge = float(user.balance_recharge or 0.0)
        withdrawable = float(user.balance_withdrawable or 0.0) # Si usas este campo
        total_balance = recharge + withdrawable
        
        # O si usas balance_total directamente:
        # total_balance = float(user.balance_total or 0.0)
        
        return {
            "status": "success",
            "user": {
                "telegram_id": user.telegram_id,
                "balance": total_balance,
                "balance_recharge": recharge,
                "balance_available": total_balance, # Para compatibilidad
                "balance_locked": float(user.balance_locked or 0.0),
                "is_verified": user.is_verified,
                "status": user.status
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user {telegram_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        session.close()
