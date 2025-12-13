# =====================================================================
# payments_core.py — Motor interno de pagos PITIUPI v5.1 (SIMPLIFICADO)
# =====================================================================

from datetime import datetime
from database import get_connection
import logging

logger = logging.getLogger(__name__)


# ============================================================
# 🟢 CREAR INTENT DE PAGO
# ============================================================
def create_payment_intent(
    telegram_id: int,
    amount: float,
) -> int:
    """
    Crea un intent de pago.
    Ahora guardamos telegram_id duplicado para búsquedas rápidas.
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Primero obtener el user_id real (si existe)
        cursor.execute(
            "SELECT id FROM users WHERE telegram_id = %s LIMIT 1",
            (telegram_id,)
        )
        user = cursor.fetchone()
        
        user_id = user["id"] if user else telegram_id  # Fallback al telegram_id

        cursor.execute(
            """
            INSERT INTO payment_intents (
                user_id,
                telegram_id,
                amount,
                status,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                user_id,
                telegram_id,
                amount,
                "pending",
                datetime.utcnow(),
            )
        )

        row = cursor.fetchone()
        conn.commit()

        intent_id = row["id"]
        logger.info(
            f"🟢 Intent {intent_id} creado | TelegramID={telegram_id}"
        )

        return intent_id

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error creando payment intent: {e}", exc_info=True)
        raise

    finally:
        if conn:
            conn.close()


# ============================================================
# 🔍 OBTENER INTENT
# ============================================================
def get_payment_intent(intent_id: int):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                user_id,
                telegram_id,
                amount,
                status,
                order_id,
                transaction_id,
                authorization_code,
                status_detail,
                created_at,
                paid_at,
                message
            FROM payment_intents
            WHERE id = %s;
            """,
            (intent_id,)
        )

        return cursor.fetchone()

    except Exception as e:
        logger.error(f"❌ Error obteniendo intent {intent_id}: {e}", exc_info=True)
        raise

    finally:
        if conn:
            conn.close()


# ============================================================
# 🔧 ACTUALIZAR INTENT
# ============================================================
def update_payment_intent(intent_id: int, **fields):
    if not fields:
        return

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [intent_id]

        cursor.execute(
            f"UPDATE payment_intents SET {set_clause} WHERE id = %s;",
            values,
        )

        conn.commit()
        logger.info(f"🔵 Intent {intent_id} actualizado → {fields}")

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error actualizando intent {intent_id}: {e}", exc_info=True)
        raise

    finally:
        if conn:
            conn.close()


# ============================================================
# 🟣 MARCAR INTENT COMO PAGADO
# ============================================================
def mark_intent_paid(
    intent_id: int,
    provider_tx_id: str,
    status_detail: int,
    authorization_code: str,
    message: str | None = None,
):
    fields = {
        "status": "paid",
        "transaction_id": provider_tx_id,
        "status_detail": status_detail,
        "authorization_code": authorization_code,
        "paid_at": datetime.utcnow(),
    }

    if message:
        fields["message"] = message

    update_payment_intent(intent_id, **fields)

    logger.info(
        f"🟢 Intent {intent_id} APROBADO ✓ tx={provider_tx_id}"
    )


# ============================================================
# 💰 SUMAR BALANCE
# ============================================================
def add_user_balance(telegram_id: int, amount: float):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # PRIMERO: Verificar si existe el usuario con ese telegram_id
        cursor.execute(
            "SELECT id FROM users WHERE telegram_id = %s",
            (telegram_id,)
        )
        user = cursor.fetchone()
        
        if not user:
            logger.error(f"❌ Usuario con telegram_id={telegram_id} no existe")
            raise ValueError(f"Usuario {telegram_id} no encontrado")

        # SEGUNDO: Actualizar balance
        cursor.execute(
            """
            UPDATE users
            SET balance = COALESCE(balance, 0) + %s
            WHERE telegram_id = %s
            RETURNING balance;
            """,
            (amount, telegram_id)
        )

        row = cursor.fetchone()
        conn.commit()

        new_balance = row["balance"]
        logger.info(
            f"💰 Balance actualizado | TelegramID={telegram_id} | Nuevo=${new_balance:.2f}"
        )

        return float(new_balance)

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error actualizando balance: {e}")
        raise
    finally:
        if conn:
            conn.close()

