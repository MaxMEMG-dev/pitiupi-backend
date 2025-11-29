from datetime import datetime
from database import get_connection

# --- CREATE PAYMENT INTENT ---
def create_payment_intent(user_id: int, amount: float) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO payment_intents (user_id, amount, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """,
        (user_id, amount, datetime.now()),
    )

    intent_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return intent_id


# --- GET PAYMENT INTENT ---
def get_payment_intent(intent_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, user_id, amount, status, created_at, transaction_id, authorization_code, status_detail FROM payment_intents WHERE id = ?",
        (intent_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "id": row[0],
            "user_id": row[1],
            "amount": row[2],
            "status": row[3],
            "created_at": row[4],
            "transaction_id": row[5],
            "authorization_code": row[6],
            "status_detail": row[7],
        }

    return None


# --- UPDATE PAYMENT INTENT ---
def update_payment_intent(intent_id: int, **fields):
    conn = get_connection()
    cursor = conn.cursor()

    set_clause = ", ".join(f"{key} = ?" for key in fields.keys())
    values = list(fields.values()) + [intent_id]

    cursor.execute(
        f"UPDATE payment_intents SET {set_clause} WHERE id = ?", values
    )

    conn.commit()
    conn.close()


# --- MARK AS PAID ---
def mark_intent_paid(intent_id: int, provider_tx_id: str, status_detail: int, authorization_code: str):
    update_payment_intent(
        intent_id,
        status="paid",
        transaction_id=provider_tx_id,
        status_detail=status_detail,
        authorization_code=authorization_code,
        paid_at=datetime.now(),
    )
