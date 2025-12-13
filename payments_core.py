# =====================================================================
# payments_core.py — Motor interno de pagos PITIUPI v5.1 (CORREGIDO)
# =====================================================================

from datetime import datetime
from database import get_connection
import logging

logger = logging.getLogger(__name__)


# ============================================================
# 🟢 CREAR INTENT DE PAGO (GUARDA application_code)
# ============================================================
def create_payment_intent(
    telegram_id: int,
    amount: float,
    application_code: str,
) -> int:
    """
    Crea un intent de pago.
    user_id = TelegramID
    application_code = NUVEI_APP_CODE_SERVER (CLAVE PARA STOKEN)
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
                application_code,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                telegram_id,
                amount,
                "pending",
                application_code,
                datetime.utcnow(),
            )
        )

        row = cursor.fetchone()
        conn.commit()

        intent_id = row["id"]
        logger.info(
            f"🟢 Intent {intent_id} creado | user={telegram_id} | app={application_code}"
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
# 🔍 OBTENER INTENT (INCLUYE application_code)
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
                amount,
                status,
                order_id,
                transaction_id,
                authorization_code,
                status_detail,
                application_code,
                created_at,
                paid_at
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
# 💰 SUMAR BALANCE (REQUIERE users.balance)
# ============================================================
def add_user_balance(telegram_id: int, amount: float):
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

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

        if not row:
            raise RuntimeError("Usuario no encontrado al actualizar balance")

        new_balance = row["balance"]
        logger.info(
            f"💰 Balance actualizado | user={telegram_id} | balance={new_balance}"
        )

        return new_balance

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(
            f"❌ Error actualizando balance para {telegram_id}: {e}",
            exc_info=True
        )
        raise

    finally:
        if conn:
            conn.close()
