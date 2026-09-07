from __future__ import annotations

from src.infrastructure.postgres.connection import get_postgres_connection
from src.publication_gate import OperationalPublicationDecision


def save_publication_decision(
    *,
    postgres_run_id: int,
    governance_run_id: str,
    decision: OperationalPublicationDecision,
    quality_score: int,
    pass_checks: int,
    warn_checks: int,
    fail_checks: int,
    critical_failures: int,
    privacy_failed_checks: int,
) -> bool:
    """Persist one authoritative operational decision idempotently."""

    connection = get_postgres_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO governance.publication_decisions (
                    postgres_run_id,
                    governance_run_id,
                    decision,
                    quality_score,
                    pass_checks,
                    warn_checks,
                    fail_checks,
                    critical_failures,
                    privacy_failed_checks
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (postgres_run_id, governance_run_id)
                DO NOTHING;
                """,
                (
                    postgres_run_id,
                    governance_run_id,
                    decision,
                    quality_score,
                    pass_checks,
                    warn_checks,
                    fail_checks,
                    critical_failures,
                    privacy_failed_checks,
                ),
            )
            inserted = cursor.rowcount == 1

        connection.commit()
        return inserted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
