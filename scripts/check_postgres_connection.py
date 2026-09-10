from src.infrastructure.postgres.connection import get_postgres_connection

with get_postgres_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT version();")
        print(cur.fetchone())