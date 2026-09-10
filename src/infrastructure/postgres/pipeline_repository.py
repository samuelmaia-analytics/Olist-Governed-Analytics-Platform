from datetime import datetime

from src.infrastructure.postgres.connection import get_postgres_connection


def start_pipeline_run(
    pipeline_name: str,
    git_commit: str | None = None,
) -> int:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO governance.pipeline_runs (
                    pipeline_name,
                    status,
                    git_commit
                )
                VALUES (%s, %s, %s)
                RETURNING run_id;
                """,
                (
                    pipeline_name,
                    "RUNNING",
                    git_commit,
                ),
            )

            run_id = cur.fetchone()[0]

        conn.commit()

    return run_id


def finish_pipeline_run(
    run_id: int,
    status: str,
    rows_processed: int | None = None,
    duration_seconds: float | None = None,
    error_message: str | None = None,
) -> None:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE governance.pipeline_runs
                SET
                    finished_at = %s,
                    status = %s,
                    rows_processed = %s,
                    duration_seconds = %s,
                    error_message = %s
                WHERE run_id = %s;
                """,
                (
                    datetime.now().astimezone(),
                    status,
                    rows_processed,
                    duration_seconds,
                    error_message,
                    run_id,
                ),
            )

        conn.commit()