from datetime import datetime
from database import get_connection
import logging

logger = logging.getLogger(__name__)

def create_payment_intent(user_id: int, amount: float) -> int:
    """
    Crea un intent de pago en PostgreSQL.
    El order_id se agregará después cuando Nuvei devuelva la orden.
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO payment_intents (
                user_id,
                amount,
                status,
                created_at
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, amount, "pending", datetime.now())
        )

        intent_id = cursor.fetchone()["id"]
        conn.commit()
        logger.info(f"Payment intent {intent_id} creado para user {user_id}")
        
        return intent_id
    except Exception as e:
        logger.error(f"Error creando payment intent: {str(e)}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def get_payment_intent(intent_id: int):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT *
            FROM payment_intents
            WHERE id = %s
            """,
            (intent_id,)
        )

        row = cursor.fetchone()
        return row
    except Exception as e:
        logger.error(f"Error obteniendo payment intent {intent_id}: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()


def update_payment_intent(intent_id: int, **fields):
    conn = None
    try:
        if not fields:
            return

        conn = get_connection()
        cursor = conn.cursor()

        set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
        values = list(fields.values()) + [intent_id]

        query = f"UPDATE payment_intents SET {set_clause} WHERE id = %s"
        
        cursor.execute(query, values)
        conn.commit()
        logger.info(f"Payment intent {intent_id} actualizado: {fields.keys()}")
    except Exception as e:
        logger.error(f"Error actualizando payment intent {intent_id}: {str(e)}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def mark_intent_paid(intent_id: int, provider_tx_id: str, status_detail: int, authorization_code: str):
    """
    Marca un pago como aprobado desde el webhook Nuvei.
    """
    try:
        update_payment_intent(
            intent_id,
            status="paid",
            transaction_id=provider_tx_id,
            status_detail=status_detail,
            authorization_code=authorization_code,
            paid_at=datetime.now()
        )
        logger.info(f"Payment intent {intent_id} marcado como pagado")
    except Exception as e:
        logger.error(f"Error marcando intent {intent_id} como pagado: {str(e)}")
        raise
