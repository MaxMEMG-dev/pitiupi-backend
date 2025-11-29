import psycopg2
from psycopg2.extras import RealDictCursor
from settings import DATABASE_URL




def get_connection():
return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)




def init_db():
conn = get_connection()
cur = conn.cursor()


cur.execute(
"""
CREATE TABLE IF NOT EXISTS payment_intents (
id SERIAL PRIMARY KEY,
provider VARCHAR(50),
user_id VARCHAR(100),
amount NUMERIC(10,2),
status VARCHAR(20),
provider_intent_id VARCHAR(100),
provider_tx_id VARCHAR(100),
authorization_code VARCHAR(50),
status_detail INTEGER,
link_url TEXT,
created_at TIMESTAMP DEFAULT NOW(),
updated_at TIMESTAMP DEFAULT NOW()
);
"""
)


conn.commit()
conn.close()