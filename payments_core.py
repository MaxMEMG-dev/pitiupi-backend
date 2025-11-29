from database import get_connection


cur.execute(
"""
INSERT INTO payment_intents (provider, user_id, amount, status, created_at, updated_at)
VALUES ('nuvei', %s, %s, 'pending', NOW(), NOW())
RETURNING id;
""",
(user_id, amount),
)


intent_id = cur.fetchone()["id"]
conn.commit()
conn.close()
return intent_id




def update_intent_link(intent_id: int, provider_intent_id: str, link_url: str):
conn = get_connection()
cur = conn.cursor()


cur.execute(
"""
UPDATE payment_intents
SET provider_intent_id=%s, link_url=%s, updated_at=NOW()
WHERE id=%s
""",
(provider_intent_id, link_url, intent_id),
)


conn.commit()
conn.close()




def mark_intent_paid(intent_id: int, provider_tx_id: str, status_detail: int, authorization_code: str):
conn = get_connection()
cur = conn.cursor()


cur.execute(
"""
UPDATE payment_intents
SET status='paid',
provider_tx_id=%s,
status_detail=%s,
authorization_code=%s,
updated_at=NOW()
WHERE id=%s
""",
(provider_tx_id, status_detail, authorization_code, intent_id),
)


conn.commit()
conn.close()