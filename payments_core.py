from datetime import datetime
from database import get_connection

def create_payment_intent(user_id: int, amount: float) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO payment_intents (user_id, amount, status, created_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, amount, "pending", datetime.now())
    )

    intent_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    return intent_id


def get_payment_intent(intent_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, user_id, amount, status, created_at, 
               transaction_id, authorization_code, status_detail, 
               paid_at, order_id
        FROM payment_intents
        WHERE id = %s
        """,
        (intent_id,)
    )

    row = cursor.fetchone()
    conn.close()

    return row


def update_payment_intent(intent_id: int, **fields):
    conn = get_connection()
    cursor = conn.cursor()

    columns = ", ".join([f"{k} = %s" for k in fields.keys()])
    values = list(fields.values()) + [intent_id]

    cursor.execute(
        f"UPDATE payment_intents SET {columns} WHERE id = %s",
        values
    )

    conn.commit()
    conn.close()


def mark_intent_paid(intent_id: int, provider_tx_id: str, status_detail: int, authorization_code: str):
    update_payment_intent(
        intent_id,
        status="paid",
        transaction_id=provider_tx_id,
        status_detail=status_detail,
        authorization_code=authorization_code,
        paid_at=datetime.now()
    )


