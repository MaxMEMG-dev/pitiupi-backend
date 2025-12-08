# =====================================================================
# payments_core.py — Motor interno de pagos PITIUPI v5.0
# Maneja intents, actualizaciones, vouchers y registro desde Webhook.
# =====================================================================

from datetime import datetime
from database import get_connection
import logging

logger = logging.getLogger(__name__)


# ============================================================
# 🟢 CREAR INTENT DE PAGO
# ============================================================
def create_payment_intent(telegram_id: int, amount: float) -> int:
    """
    Crea un intent de pago.
    user_id = TelegramID (no el ID interno del usuario)
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
            (telegram_id, amount, "pending", datetime.now())
        )

        row = cursor.fetchone()
        intent_id = row["id"]

        conn.commit()
        logger.info(f"🟢 Intent {intent_id} creado para TelegramID={telegram_id}")

        return intent_id

    except Exception as e:
        logger.error(f"❌ Error creando payment intent: {e}")
        if conn:
            conn.rollback()
        raise

    finally:
        if conn:
            conn.close()



# ============================================================
# 🔍 OBTENER INTENT (para voucher del bot)
# ============================================================
def get_payment_intent(intent_id: int):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, user_id, amount, status, order_id, transaction_id,
                   authorization_code, status_detail, created_at, paid_at
            FROM payment_intents
            WHERE id = %s
            """,
            (intent_id,)
        )

        row = cursor.fetchone()
        return row

    except Exception as e:
        logger.error(f"❌ Error obteniendo intent {intent_id}: {e}")
        raise

    finally:
        if conn:
            conn.close()



# ============================================================
# 🔧 ACTUALIZAR CAMPOS DEL INTENT
# ============================================================
def update_payment_intent(intent_id: int, **fields):
    """
    Actualiza uno o más campos del intent.
    Ejemplo:
        update_payment_intent(55, order_id='XYZ', status='waiting')
    """
    if not fields:
        return

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
        values = list(fields.values()) + [intent_id]

        query = f"UPDATE payment_intents SET {set_clause} WHERE id = %s"

        cursor.execute(query, values)
        conn.commit()

        logger.info(f"🔵 Intent {intent_id} actualizado → {fields}")

    except Exception as e:
        logger.error(f"❌ Error actualizando intent {intent_id}: {e}")
        if conn:
            conn.rollback()
        raise

    finally:
        if conn:
            conn.close()



# ============================================================
# 🟣 MARCAR INTENT COMO PAGADO (WEBHOOK NUVEI)
# ============================================================
def mark_intent_paid(
    intent_id: int,
    provider_tx_id: str,
    status_detail: int,
    authorization_code: str,
    message: str = None,
):
    """
    Marca el pago como aprobado desde el Webhook Nuvei.
    Guarda información del voucher.
    """

    fields = {
        "status": "paid",
        "transaction_id": provider_tx_id,
        "status_detail": status_detail,
        "authorization_code": authorization_code,
        "paid_at": datetime.now(),
    }

    if message:
        fields["message"] = message  # por si agregas columna message después

    try:
        update_payment_intent(intent_id, **fields)
        logger.info(f"🟢 Intent {intent_id} APROBADO ✓ proveedor={provider_tx_id}")

    except Exception as e:
        logger.error(
            f"❌ Error marcando intent {intent_id} como pagado: {e}",
            exc_info=True
        )
        raise
