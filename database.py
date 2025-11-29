import psycopg2
from psycopg2.extras import RealDictCursor
import os


DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_intents (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount NUMERIC NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            transaction_id VARCHAR(255),
            authorization_code VARCHAR(255),
            status_detail INTEGER,
            paid_at TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()
