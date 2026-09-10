from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import ANALYTICS_DIR, DOCS_DIR, QUALITY_DIR
from src.ingest import configure_logging
from src.quality_components.models import QualityCheckResult as QualityCheckResult
from src.utils import ensure_directory

LOGGER = logging.getLogger(__name__)
FACT_TABLE_PATH = ANALYTICS_DIR / "fact_orders_enriched.parquet"
QUALITY_RESULTS_PATH = QUALITY_DIR / "fact_orders_enriched_quality_checks.csv"
QUALITY_REPORT_PATH = DOCS_DIR / "data_quality_report.md"

EXPECTED_COLUMNS = {
    "order_id",
    "order_item_id",
    "customer_id",
    "product_id",
    "seller_id",
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
    "price",
    "freight_value",
    "review_score_mean",
    "product_category_name",
    "order_year",
    "order_month",
    "order_date",
    "delivery_time_days",
    "estimated_delay_days",
    "is_delayed",
    "total_item_value",
}
CRITICAL_COLUMNS = [
    "order_id",
    "order_item_id",
    "customer_id",
    "product_id",
    "seller_id",
    "order_purchase_timestamp",
    "price",
    "freight_value",
]
GRANULARITY_COLUMNS = ["order_id", "order_item_id", "product_id", "seller_id"]
MAX_REVIEW_SCORE_MISSING_PCT = 35.0
MAX_CATEGORY_MISSING_PCT = 5.0
MAX_UNDELIVERED_PCT = 5.0
MAX_DIMENSION_JOIN_MISSING_PCT = 1.0
MAX_PAYMENT_GAP_OVER_1_REAL_PCT = 5.0
MAX_DELIVERY_BEFORE_APPROVAL_PCT = 0.1
MIN_RECORDS = 100_001


def validate_not_empty(df: pd.DataFrame, dataset_name: str) -> None:
    if df.empty:
        raise ValueError(f"{dataset_name} is empty.")


def load_fact_table() -> pd.DataFrame:
    if not FACT_TABLE_PATH.exists():
        raise FileNotFoundError(f"Tabela analítica não encontrada: {FACT_TABLE_PATH}")

    df = pd.read_parquet(FACT_TABLE_PATH)
    validate_not_empty(df, "fact_orders_enriched")
    LOGGER.info("Tabela carregada para validação | shape=(%s, %s)", *df.shape)
    return df


def build_result(
    check_name: str,
    passed: bool,
    metric_value: float | str,
    threshold: float | str,
    severity: str,
    details: str,
) -> QualityCheckResult:
    return QualityCheckResult(
        check_name=check_name,
        status="PASS" if passed else "FAIL",
        metric_value=metric_value,
        threshold=threshold,
        severity=severity,
        details=details,
    )


def check_expected_schema(df: pd.DataFrame) -> QualityCheckResult:
    missing_columns = sorted(EXPECTED_COLUMNS.difference(df.columns))
    unexpected_columns = sorted(set(df.columns).difference(EXPECTED_COLUMNS))
    passed = not missing_columns
    details = (
        f"Ausentes: {missing_columns if missing_columns else 'nenhuma'} | "
        f"Inesperadas: {unexpected_columns if unexpected_columns else 'nenhuma'}"
    )
    return build_result(
        "expected_schema",
        passed,
        len(missing_columns),
        0,
        "high",
        details,
    )


def check_critical_nulls(df: pd.DataFrame) -> list[QualityCheckResult]:
    results: list[QualityCheckResult] = []
    for column in CRITICAL_COLUMNS:
        null_count = int(df[column].isna().sum())
        passed = null_count == 0
        results.append(
            build_result(
                f"critical_nulls__{column}",
                passed,
                null_count,
                0,
                "high",
                f"A coluna `{column}` possui {null_count} valores nulos.",
            )
        )
    return results


def check_granularity_duplicates(df: pd.DataFrame) -> QualityCheckResult:
    duplicate_count = int(df.duplicated(subset=GRANULARITY_COLUMNS, keep=False).sum())
    passed = duplicate_count == 0
    return build_result(
        "granularity_duplicates",
        passed,
        duplicate_count,
        0,
        "high",
        f"Colunas de granularidade: {', '.join(GRANULARITY_COLUMNS)}",
    )


def check_negative_values(df: pd.DataFrame) -> list[QualityCheckResult]:
    price_negative = int((df["price"].fillna(0) < 0).sum())
    freight_negative = int((df["freight_value"].fillna(0) < 0).sum())
    return [
        build_result(
            "negative_price_values",
            price_negative == 0,
            price_negative,
            0,
            "high",
            (
                "Foram encontrados valores negativos em `price`."
                if price_negative
                else "Não foram encontrados valores negativos em `price`."
            ),
        ),
        build_result(
            "negative_freight_values",
            freight_negative == 0,
            freight_negative,
            0,
            "high",
            (
                "Foram encontrados valores negativos em `freight_value`."
                if freight_negative
                else "Não foram encontrados valores negativos em `freight_value`."
            ),
        ),
    ]


def check_temporal_coherence(df: pd.DataFrame) -> list[QualityCheckResult]:
    approval_before_purchase = int(
        (
            df["order_approved_at"].notna()
            & df["order_purchase_timestamp"].notna()
            & (df["order_approved_at"] < df["order_purchase_timestamp"])
        ).sum()
    )
    delivery_before_purchase = int(
        (
            df["order_delivered_customer_date"].notna()
            & df["order_purchase_timestamp"].notna()
            & (df["order_delivered_customer_date"] < df["order_purchase_timestamp"])
        ).sum()
    )
    delivery_before_approval = int(
        (
            df["order_delivered_customer_date"].notna()
            & df["order_approved_at"].notna()
            & (df["order_delivered_customer_date"] < df["order_approved_at"])
        ).sum()
    )
    delivery_before_approval_pct = (
        round((delivery_before_approval / len(df)) * 100, 4) if len(df) else 0.0
    )
    delivery_before_approval_status = "PASS"
    delivery_before_approval_details = "Orders delivered before approval timestamp."
    if delivery_before_approval_pct > MAX_DELIVERY_BEFORE_APPROVAL_PCT:
        delivery_before_approval_status = "FAIL"
    elif delivery_before_approval > 0:
        delivery_before_approval_status = "WARN"
        delivery_before_approval_details = (
            f"{delivery_before_approval_details} Residual source issue within "
            f"the operational tolerance of {MAX_DELIVERY_BEFORE_APPROVAL_PCT}%."
        )
    return [
        build_result(
            "temporal_coherence__approval_before_purchase",
            approval_before_purchase == 0,
            approval_before_purchase,
            0,
            "medium",
            "Pedidos aprovados antes do timestamp de compra.",
        ),
        build_result(
            "temporal_coherence__delivery_before_purchase",
            delivery_before_purchase == 0,
            delivery_before_purchase,
            0,
            "high",
            "Pedidos entregues antes do timestamp de compra.",
        ),
        QualityCheckResult(
            check_name="temporal_coherence__delivery_before_approval",
            status=delivery_before_approval_status,
            metric_value=delivery_before_approval,
            threshold=MAX_DELIVERY_BEFORE_APPROVAL_PCT,
            severity="medium",
            details=delivery_before_approval_details,
        ),
    ]


def check_review_score_missing_pct(df: pd.DataFrame) -> QualityCheckResult:
    missing_pct = round(float(df["review_score_mean"].isna().mean() * 100), 2)
    passed = missing_pct <= MAX_REVIEW_SCORE_MISSING_PCT
    return build_result(
        "review_score_missing_pct",
        passed,
        missing_pct,
        MAX_REVIEW_SCORE_MISSING_PCT,
        "medium",
        "Percentual de registros sem `review_score_mean`.",
    )


def check_category_missing_pct(df: pd.DataFrame) -> QualityCheckResult:
    missing_pct = round(float(df["product_category_name"].isna().mean() * 100), 2)
    passed = missing_pct <= MAX_CATEGORY_MISSING_PCT
    return build_result(
        "category_missing_pct",
        passed,
        missing_pct,
        MAX_CATEGORY_MISSING_PCT,
        "medium",
        "Percentual de registros sem `product_category_name`.",
    )


def check_undelivered_pct(df: pd.DataFrame) -> QualityCheckResult:
    undelivered_pct = round(
        float(df["order_delivered_customer_date"].isna().mean() * 100), 2
    )
    passed = undelivered_pct <= MAX_UNDELIVERED_PCT
    return build_result(
        "undelivered_orders_pct",
        passed,
        undelivered_pct,
        MAX_UNDELIVERED_PCT,
        "medium",
        "Percentual de registros sem data final de entrega ao cliente.",
    )


def check_delay_null_consistency(df: pd.DataFrame) -> QualityCheckResult:
    inconsistent_count = int(
        (
            df["order_delivered_customer_date"].isna()
            & df["estimated_delay_days"].notna()
        ).sum()
        + (
            df["order_delivered_customer_date"].notna()
            & df["estimated_delay_days"].isna()
        ).sum()
    )
    return build_result(
        "delay_null_consistency",
        inconsistent_count == 0,
        inconsistent_count,
        0,
        "high",
        "Consistencia entre data de entrega e preenchimento de `estimated_delay_days`.",
    )


def check_record_volume(df: pd.DataFrame) -> QualityCheckResult:
    total_records = int(len(df))
    passed = total_records >= MIN_RECORDS
    return build_result(
        "record_volume_above_100k",
        passed,
        total_records,
        MIN_RECORDS,
        "high",
        "Total de registros na tabela final.",
    )


def check_dimension_join_coverage(df: pd.DataFrame) -> list[QualityCheckResult]:
    results: list[QualityCheckResult] = []
    for column in [
        "customer_unique_id",
        "customer_state",
        "seller_state",
        "payment_type_mode",
    ]:
        if column not in df.columns:
            results.append(
                build_result(
                    f"dimension_join_missing_pct__{column}",
                    False,
                    100.0,
                    MAX_DIMENSION_JOIN_MISSING_PCT,
                    "medium",
                    f"Coluna `{column}` ausente da tabela.",
                )
            )
            continue
        missing_pct = round(float(df[column].isna().mean() * 100), 2)
        results.append(
            build_result(
                f"dimension_join_missing_pct__{column}",
                missing_pct <= MAX_DIMENSION_JOIN_MISSING_PCT,
                missing_pct,
                MAX_DIMENSION_JOIN_MISSING_PCT,
                "medium",
                f"Percentual de ausência do atributo enriquecido `{column}` na tabela final.",
            )
        )
    return results


def check_payment_reconciliation(df: pd.DataFrame) -> QualityCheckResult:
    order_level = (
        df.groupby("order_id", as_index=False)
        .agg(
            order_items_total=("total_item_value", "sum"),
            order_payment_total=("total_payment_value", "max"),
        )
        .assign(
            order_payment_total=lambda frame: frame["order_payment_total"].fillna(0),
            abs_gap=lambda frame: (
                frame["order_items_total"] - frame["order_payment_total"]
            ).abs(),
        )
    )
    gap_pct = round(float((order_level["abs_gap"] > 1.0).mean() * 100), 2)
    passed = gap_pct <= MAX_PAYMENT_GAP_OVER_1_REAL_PCT
    return build_result(
        "payment_reconciliation_gap_over_1_real_pct",
        passed,
        gap_pct,
        MAX_PAYMENT_GAP_OVER_1_REAL_PCT,
        "medium",
        "Percentual de pedidos com diferenca superior a R$ 1,00 entre `sum(total_item_value)` e `total_payment_value`.",
    )


def run_quality_checks(df: pd.DataFrame) -> list[QualityCheckResult]:
    results: list[QualityCheckResult] = []
    results.append(check_expected_schema(df))
    results.extend(check_critical_nulls(df))
    results.append(check_granularity_duplicates(df))
    results.extend(check_negative_values(df))
    results.extend(check_temporal_coherence(df))
    results.append(check_review_score_missing_pct(df))
    results.append(check_category_missing_pct(df))
    results.append(check_undelivered_pct(df))
    results.append(check_delay_null_consistency(df))
    results.extend(check_dimension_join_coverage(df))
    results.append(check_payment_reconciliation(df))
    results.append(check_record_volume(df))
    return results


def save_quality_results(results: list[QualityCheckResult]) -> Path:
    ensure_directory(QUALITY_DIR)
    results_df = pd.DataFrame(asdict(result) for result in results)
    results_df.to_csv(QUALITY_RESULTS_PATH, index=False)
    LOGGER.info("Resultados de qualidade salvos em %s", QUALITY_RESULTS_PATH)
    return QUALITY_RESULTS_PATH


def render_quality_report(df: pd.DataFrame, results: list[QualityCheckResult]) -> str:
    results_df = pd.DataFrame(asdict(result) for result in results)
    failed_df = results_df[results_df["status"] == "FAIL"]
    has_residual_source_issue = bool(
        (
            (results_df["check_name"] == "temporal_coherence__delivery_before_approval")
            & results_df["status"].isin(["FAIL", "WARN"])
            if not results_df.empty
            else pd.Series(dtype=bool)
        ).any()
    )

    lines = [
        "# Relatório de Qualidade de Dados",
        "",
        "Relatório de validação da tabela `fact_orders_enriched`.",
        "",
        "## Resumo",
        "",
        f"- Total de registros avaliados: **{len(df):,}**",
        f"- Total de colunas avaliadas no dataset: **{df.shape[1]}**",
        f"- Total de checks executados: **{len(results)}**",
        f"- Checks aprovados: **{int((results_df['status'] == 'PASS').sum())}**",
        f"- Checks reprovados: **{int((results_df['status'] == 'FAIL').sum())}**",
        "",
        "## Resultado dos Checks",
        "",
        "| Check | Status | Valor | Threshold | Severidade |",
        "| --- | --- | ---: | ---: | --- |",
    ]

    for row in results_df.itertuples(index=False):
        lines.append(
            f"| `{row.check_name}` | **{row.status}** | {row.metric_value} | {row.threshold} | {row.severity} |"
        )

    lines.extend(["", "## Observações", ""])

    if failed_df.empty:
        lines.append("- Nenhum check falhou na validação atual.")
    else:
        for row in failed_df.itertuples(index=False):
            lines.append(
                f"- `{row.check_name}`: {row.details} Valor observado={row.metric_value}."
            )

    if has_residual_source_issue:
        lines.extend(
            [
                "",
                "## Nota sobre a Falha Residual",
                "",
                "- A falha em `delivery_before_approval` indica uma inconsistência pontual presente nos dados de origem.",
                "- O pipeline atual preserva esse comportamento para manter rastreabilidade sobre a fonte, em vez de mascarar o problema com correções arbitrárias.",
                "- Como o volume afetado é baixo frente ao total da base, o ponto foi mantido como alerta de qualidade e não como bloqueio da camada analítica.",
            ]
        )

    lines.extend(
        [
            "",
            "## Regras Avaliadas",
            "",
            "- Presença do schema mínimo esperado para consumo analítico.",
            "- Ausência de nulos em colunas críticas de identificação e valor.",
            "- Ausência de duplicidade na granularidade `order_id + order_item_id + product_id + seller_id`.",
            "- Ausência de valores negativos em preço e frete.",
            "- Coerência temporal entre compra, aprovação e entrega.",
            "- Percentual de ausência de review score dentro do limite aceitável.",
            "- Percentual de ausência de categoria dentro do limite aceitável.",
            "- Percentual de pedidos sem entrega final dentro do limite aceitável.",
            "- Consistência entre ausência de entrega e ausência de `estimated_delay_days`.",
            "- Cobertura mínima dos principais atributos enriquecidos da camada dimensional.",
            "- Reconciliação financeira entre valor do pedido na grain analítica e total pago por pedido.",
            "- Volume total acima de 100.000 registros.",
            "",
        ]
    )
    return "\n".join(lines)


def save_quality_report(df: pd.DataFrame, results: list[QualityCheckResult]) -> Path:
    ensure_directory(DOCS_DIR)
    QUALITY_REPORT_PATH.write_text(render_quality_report(df, results), encoding="utf-8")
    LOGGER.info("Relatório de qualidade salvo em %s", QUALITY_REPORT_PATH)
    return QUALITY_REPORT_PATH


def main() -> None:
    configure_logging()
    df = load_fact_table()
    results = run_quality_checks(df)
    save_quality_results(results)
    save_quality_report(df, results)


if __name__ == "__main__":
    main()
