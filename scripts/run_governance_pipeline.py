from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from . import n8n_utils as _package_n8n_utils
except ImportError:  # pragma: no cover - direct script execution
    import n8n_utils as _direct_n8n_utils

    load_config = _direct_n8n_utils.load_config
else:
    load_config = _package_n8n_utils.load_config
from src.ingest import configure_logging
from src.infrastructure.postgres.pipeline_repository import (
    finish_pipeline_run,
    start_pipeline_run,
)
from src.infrastructure.postgres.publication_decision_repository import (
    save_publication_decision,
)
from src.infrastructure.postgres.quality_repository import (
    save_quality_results,
)
from src.publication_gate import (
    OperationalPublicationGateDecision,
    evaluate_operational_publication_gate,
)
from src.publication_provenance import PipelineGovernanceContext
from src.publish_dashboard import run_privacy_preflight
from src.quality_components.models import QualityCheckResult
from src.run_platform_pipeline import (
    StepExecution,
    activate_pipeline_governance_context,
    build_pipeline_run_id,
    build_run_metadata,
    resolve_steps,
    run_selected_steps,
    save_pipeline_execution_report,
)


@dataclass(frozen=True)
class GovernedPipelineExecution:
    executions: tuple[StepExecution, ...]
    publication_gate: OperationalPublicationGateDecision | None
    quality_results_persisted: int
    rows_processed: int | None
    postgres_run_id: int
    governance_run_id: str


def _configured_steps(
    config: dict[str, object],
) -> list[str] | None:
    pipeline_config = cast(
        dict[str, object],
        config.get("pipeline", {}),
    )
    steps = cast(
        Sequence[object] | None,
        pipeline_config.get("default_steps"),
    )

    if not steps:
        return None

    return [
        str(step)
        for step in steps
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "n8n wrapper for the governed pipeline "
            "with PostgreSQL publication gate."
        )
    )

    parser.add_argument(
        "--config",
        default="config/pipeline_config.yml",
    )

    parser.add_argument(
        "--steps",
        nargs="*",
        help="Optional explicit pipeline steps.",
    )

    parser.add_argument(
        "--continue-on-error",
        action="store_true",
    )

    return parser.parse_args()


def extract_rows_processed(
    quality_results: Sequence[QualityCheckResult],
) -> int | None:
    volume_result = next(
        (
            result
            for result in quality_results
            if result.check_name
            == "record_volume_above_100k"
        ),
        None,
    )
    if volume_result is None:
        return None

    try:
        return int(
            float(volume_result.metric_value)
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def persist_quality_results_to_postgres(
    postgres_run_id: int,
    quality_results: Sequence[QualityCheckResult],
) -> int:
    return save_quality_results(
        run_id=postgres_run_id,
        dataset_name="fact_orders_enriched",
        results=quality_results,
    )


def evaluate_current_quality_gate(
    quality_results: Sequence[QualityCheckResult],
    *,
    privacy_failed_checks: int,
) -> OperationalPublicationGateDecision:
    return evaluate_operational_publication_gate(
        total_checks=len(quality_results),
        pass_checks=sum(
            result.status.upper() == "PASS"
            for result in quality_results
        ),
        warn_checks=sum(
            result.status.upper() == "WARN"
            for result in quality_results
        ),
        fail_checks=sum(
            result.status.upper() == "FAIL"
            for result in quality_results
        ),
        critical_failures=sum(
            result.status.upper() == "FAIL"
            and result.severity.strip().lower()
            in {"high", "critical"}
            for result in quality_results
        ),
        privacy_failed_checks=privacy_failed_checks,
    )


def split_pipeline_for_gate(
    selected_steps: list[str],
) -> tuple[
    list[str],
    list[str],
]:
    if "publish" not in selected_steps:
        return (
            selected_steps,
            [],
        )

    publish_index = (
        selected_steps.index(
            "publish"
        )
    )

    pre_publish_steps = (
        selected_steps[
            :publish_index
        ]
    )

    post_gate_steps = (
        selected_steps[
            publish_index:
        ]
    )

    if "quality" not in pre_publish_steps:
        raise RuntimeError(
            "Publication Gate recusou a "
            "execução: a etapa 'quality' "
            "deve ser executada antes de "
            "'publish'."
        )

    return (
        pre_publish_steps,
        post_gate_steps,
    )


def execute_governed_steps(
    *,
    selected_steps: list[str],
    continue_on_error: bool,
    postgres_run_id: int,
    governance_context: PipelineGovernanceContext,
) -> GovernedPipelineExecution:
    pre_publish_steps, post_gate_steps = split_pipeline_for_gate(
        selected_steps
    )
    executions: list[StepExecution] = []
    publication_gate: OperationalPublicationGateDecision | None = None
    persisted_count = 0
    rows_processed: int | None = None

    with activate_pipeline_governance_context(governance_context):
        executions.extend(
            run_selected_steps(
                pre_publish_steps,
                continue_on_error=continue_on_error,
            )
        )

        if "quality" in pre_publish_steps:
            quality_results = tuple(
                governance_context.quality_results or ()
            )
            rows_processed = extract_rows_processed(
                quality_results
            )
            if quality_results:
                persisted_count = persist_quality_results_to_postgres(
                    postgres_run_id,
                    quality_results,
                )

            if post_gate_steps:
                privacy_preflight = run_privacy_preflight()
                governance_context.record_current_privacy(
                    privacy_preflight.source_df,
                    privacy_preflight.published_candidate,
                    privacy_preflight.checks,
                    produced_at=datetime.now(UTC),
                    execution_step="privacy_preflight",
                )
                publication_gate = evaluate_current_quality_gate(
                    quality_results,
                    privacy_failed_checks=privacy_preflight.failed_checks,
                )
                save_publication_decision(
                    postgres_run_id=postgres_run_id,
                    governance_run_id=governance_context.run_id,
                    decision=publication_gate.decision,
                    quality_score=publication_gate.quality_score,
                    pass_checks=publication_gate.pass_checks,
                    warn_checks=publication_gate.warn_checks,
                    fail_checks=publication_gate.fail_checks,
                    critical_failures=publication_gate.critical_failures,
                    privacy_failed_checks=(
                        publication_gate.privacy_failed_checks
                    ),
                )
                if publication_gate.decision == "BLOCKED":
                    return GovernedPipelineExecution(
                        executions=tuple(executions),
                        publication_gate=publication_gate,
                        quality_results_persisted=persisted_count,
                        rows_processed=rows_processed,
                        postgres_run_id=postgres_run_id,
                        governance_run_id=governance_context.run_id,
                    )

        if post_gate_steps:
            executions.extend(
                run_selected_steps(
                    post_gate_steps,
                    continue_on_error=continue_on_error,
                )
            )

    return GovernedPipelineExecution(
        executions=tuple(executions),
        publication_gate=publication_gate,
        quality_results_persisted=persisted_count,
        rows_processed=rows_processed,
        postgres_run_id=postgres_run_id,
        governance_run_id=governance_context.run_id,
    )


def main() -> None:
    args = parse_args()

    config = load_config(
        PROJECT_ROOT
        / args.config
    )

    configured_continue = bool(
        config.get(
            "pipeline",
            {},
        ).get(
            "continue_on_error",
            False,
        )
    )

    continue_on_error = (
        args.continue_on_error
        or configured_continue
    )

    selected_steps = resolve_steps(
        args.steps
        or _configured_steps(
            config
        )
    )

    configure_logging()

    started_at = datetime.now(
        UTC
    )

    started_timer = (
        perf_counter()
    )

    executions: list[StepExecution] = []

    status = "success"
    error_message = ""

    postgres_run_id = (
        start_pipeline_run(
            pipeline_name=(
                "governed_analytics_pipeline"
            ),
        )
    )

    quality_results_persisted = 0

    rows_processed: int | None = None

    publication_gate: OperationalPublicationGateDecision | None = None
    governance_context = PipelineGovernanceContext(
        run_id=build_pipeline_run_id(started_at),
        started_at=started_at,
    )

    try:
        outcome = execute_governed_steps(
            selected_steps=selected_steps,
            continue_on_error=continue_on_error,
            postgres_run_id=postgres_run_id,
            governance_context=governance_context,
        )
        executions.extend(outcome.executions)
        publication_gate = outcome.publication_gate
        quality_results_persisted = outcome.quality_results_persisted
        rows_processed = outcome.rows_processed

        if publication_gate is not None:
            print(
                json.dumps(
                    {
                        "event": "publication_gate",
                        "postgres_run_id": postgres_run_id,
                        **asdict(publication_gate),
                    },
                    ensure_ascii=False,
                )
            )

            if publication_gate.decision == "BLOCKED":
                raise RuntimeError(
                    "Publication Gate: " + publication_gate.reason
                )

    except BaseException as exc:
        status = "failed"
        error_message = str(exc)
        raise

    finally:
        completed_at = datetime.now(
            UTC
        )

        metadata = (
            build_run_metadata(
                started_at,
                completed_at,
            )
        )

        results_path, report_path = (
            save_pipeline_execution_report(
                selected_steps,
                executions,
                metadata,
            )
        )

        duration_seconds = round(
            (
                perf_counter()
                - started_timer
            ),
            2,
        )

        finish_pipeline_run(
            run_id=postgres_run_id,
            status=status.upper(),
            rows_processed=(
                rows_processed
            ),
            duration_seconds=(
                duration_seconds
            ),
            error_message=(
                error_message
                or None
            ),
        )

        payload = {
            "status": status,
            "error_message": (
                error_message
            ),
            "run_id": (
                metadata.run_id
            ),
            "postgres_run_id": (
                postgres_run_id
            ),
            "rows_processed": (
                rows_processed
            ),
            "duration_seconds": (
                duration_seconds
            ),
            "quality_results_persisted": (
                quality_results_persisted
            ),
            "publication_gate": (
                asdict(publication_gate)
                if publication_gate is not None
                else None
            ),
            "selected_steps": (
                selected_steps
            ),
            "results_path": str(
                results_path
            ),
            "report_path": str(
                report_path
            ),
        }

        print(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
