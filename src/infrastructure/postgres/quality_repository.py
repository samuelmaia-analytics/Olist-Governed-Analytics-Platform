import json
from collections.abc import Sequence
from typing import Any

from src.infrastructure.postgres.connection import get_postgres_connection
from src.quality_components.models import QualityCheckResult


def save_quality_result(
    run_id: int,
    check_name: str,
    dataset_name: str,
    check_type: str,
    status: str,
    expected_value: str | None = None,
    actual_value: str | None = None,
    severity: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO governance.data_quality_results (
                    run_id,
                    check_name,
                    dataset_name,
                    check_type,
                    status,
                    expected_value,
                    actual_value,
                    severity,
                    details
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
                    %s::jsonb
                )
                RETURNING result_id;
                """,
                (
                    run_id,
                    check_name,
                    dataset_name,
                    check_type,
                    status,
                    expected_value,
                    actual_value,
                    severity,
                    json.dumps(details) if details is not None else None,
                ),
            )

            result_id = cur.fetchone()[0]

        conn.commit()

    return result_id


def save_quality_results(
    *,
    run_id: int,
    dataset_name: str,
    results: Sequence[QualityCheckResult],
) -> int:
    """Persist one run's quality evidence atomically and reject duplicates."""

    if not results:
        return 0

    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM governance.data_quality_results
                WHERE run_id = %s;
                """,
                (run_id,),
            )
            existing_count = int(cur.fetchone()[0])
            if existing_count > 0:
                raise RuntimeError(
                    "Data Quality results already exist for "
                    f"PostgreSQL run_id={run_id}."
                )

            cur.executemany(
                """
                INSERT INTO governance.data_quality_results (
                    run_id,
                    check_name,
                    dataset_name,
                    check_type,
                    status,
                    expected_value,
                    actual_value,
                    severity,
                    details
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
                    %s::jsonb
                );
                """,
                [
                    (
                        run_id,
                        result.check_name,
                        dataset_name,
                        "DATA_QUALITY",
                        result.status.upper(),
                        str(result.threshold),
                        str(result.metric_value),
                        result.severity.upper(),
                        json.dumps(
                            {
                                "details": result.details,
                                "source": "src.quality",
                            }
                        ),
                    )
                    for result in results
                ],
            )
        conn.commit()

    return len(results)


def get_quality_summary(run_id: int) -> dict[str, int]:
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_checks,
                    COUNT(*) FILTER (
                        WHERE status = 'PASS'
                    ) AS pass_checks,
                    COUNT(*) FILTER (
                        WHERE status = 'WARN'
                    ) AS warn_checks,
                    COUNT(*) FILTER (
                        WHERE status = 'FAIL'
                    ) AS fail_checks,
                    COUNT(*) FILTER (
                        WHERE status = 'FAIL'
                        AND severity = 'HIGH'
                    ) AS critical_failures
                FROM governance.data_quality_results
                WHERE run_id = %s;
                """,
                (run_id,),
            )

            row = cur.fetchone()

    if row is None:
        return {
            "total_checks": 0,
            "pass_checks": 0,
            "warn_checks": 0,
            "fail_checks": 0,
            "critical_failures": 0,
        }

    return {
        "total_checks": int(row[0]),
        "pass_checks": int(row[1]),
        "warn_checks": int(row[2]),
        "fail_checks": int(row[3]),
        "critical_failures": int(row[4]),
    }


def calculate_quality_score(run_id: int) -> int:
    summary = get_quality_summary(run_id)

    total_checks = summary["total_checks"]

    if total_checks == 0:
        return 0

    pass_checks = summary["pass_checks"]

    return round(
        (pass_checks / total_checks) * 100
    )
