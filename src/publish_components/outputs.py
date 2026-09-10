from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from src.publish_components.models import PrivacyCheck, PublishedArtifacts
from src.utils import ensure_directory


def save_privacy_results(
    checks: list[PrivacyCheck],
    *,
    quality_dir: Path,
    results_path: Path,
    logger: logging.Logger,
) -> Path:
    ensure_directory(quality_dir)
    pd.DataFrame(asdict(check) for check in checks).to_csv(results_path, index=False)
    logger.info("Resultados de privacidade salvos em %s", results_path)
    return results_path


def save_outputs(
    df: pd.DataFrame,
    *,
    published_dir: Path,
    parquet_path: Path,
    csv_path: Path,
    logger: logging.Logger,
) -> PublishedArtifacts:
    ensure_directory(published_dir)
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    logger.info(
        "Camada publicada do dashboard salva em %s e %s",
        parquet_path,
        csv_path,
    )
    return PublishedArtifacts(
        parquet_path=parquet_path,
        csv_path=csv_path,
        rows=len(df),
        columns=df.shape[1],
    )


def render_report(
    artifacts: PublishedArtifacts,
    contract: dict[str, Any],
    policy: dict[str, Any],
    checks: list[PrivacyCheck],
    *,
    removed_sensitive_columns: Iterable[str],
    published_parquet_path: Path,
    published_csv_path: Path,
    privacy_results_path: Path,
    to_relative_path_fn: Callable[[Path], str],
) -> str:
    principles = contract.get("lgpd_principles", [])
    validation_summary = (
        "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
    )
    lines = [
        "# Privacidade, LGPD e Governança",
        "",
        "Este documento registra as decisões de privacidade por design e governança aplicadas ao projeto.",
        "",
        "## Controles Alinhados à LGPD",
        "",
        "O projeto usa o dataset público da Olist como caso analítico, mas aplica controles inspirados em privacidade por design para reduzir exposição desnecessária na camada publicada.",
    ]
    if isinstance(principles, list):
        for principle in principles:
            if isinstance(principle, dict):
                lines.append(
                    f"- `{principle.get('principle')}`: {principle.get('control')}"
                )

    lines.extend(
        [
            "",
            "## Política LGPD Versionada",
            "",
            f"- Domínio: `{policy.get('domain', '-')}`",
            f"- Versão: `v{policy.get('version', '-')}`",
            f"- Vigência: `{policy.get('effective_date', '-')}`",
            f"- Owner: `{policy.get('owner', '-')}`",
            "",
            "## Camadas de Exposição",
            "",
            "- `data/raw/landing/`: dados brutos recebidos sem transformação.",
            "- `data/standardized/`: dados padronizados para reuso técnico.",
            "- `data/curated/analytics/`: tabela analítica interna com granularidade por item, usada para processamento, SQL e qualidade.",
            "- `data/published/dashboard/`: camada publicada e minimizada para consumo do Streamlit.",
            "",
            "## Medidas Aplicadas na Camada Publicada",
            "",
            "- pseudonimização não reversível de `order_id` e `customer_unique_id` antes do consumo pelo dashboard.",
            "- pseudonimização não reversível de `seller_id` em `seller_key` para permitir recortes por seller sem expor o identificador bruto.",
            "- remoção de identificadores desnecessários para apresentação, como `customer_id`, `seller_id` e `product_id`.",
            "- remoção de quase-identificadores mais sensíveis na camada publicada, como cidade e prefixo de CEP.",
            "- manutenção apenas de atributos necessários para responder às perguntas do projeto: tempo, categoria, UF, pagamento, valor, atraso, seller, logística e cohort.",
            "- preservação da camada analítica interna para engenharia e auditoria, separada da camada publicada.",
            "",
            "## Colunas Removidas da Camada Publicada",
            "",
            "| Coluna removida | Motivo principal |",
            "| --- | --- |",
        ]
    )
    for column in removed_sensitive_columns:
        lines.append(
            f"| `{column}` | Minimização e redução de risco de reidentificação sem perda do objetivo analítico do dashboard. |"
        )

    lines.extend(
        [
            "",
            "## Resultado da Publicação Segura",
            "",
            f"- Arquivo publicado para o app: `{to_relative_path_fn(published_parquet_path)}`",
            f"- Arquivo publicado para upload manual: `{to_relative_path_fn(published_csv_path)}`",
            f"- Registros publicados: **{artifacts.rows:,}**",
            f"- Colunas publicadas: **{artifacts.columns}**",
            f"- Resultado da validação LGPD/governança: **{validation_summary}**",
            f"- Evidência tabular dos checks: `{to_relative_path_fn(privacy_results_path)}`",
            "",
            "## Validação Aplicada",
            "",
            "| Check | Status | Detalhes |",
            "| --- | --- | --- |",
        ]
    )
    for check in checks:
        lines.append(f"| `{check.check_name}` | **{check.status}** | {check.details} |")

    lines.extend(
        [
            "",
            "## Política de Uso",
            "",
            "- o dashboard deve consumir exclusivamente a camada `published/dashboard`.",
            "- a camada `curated/analytics` permanece interna ao pipeline e não deve ser tratada como camada de exposição.",
            "- tabelas detalhadas do app devem exibir apenas chaves pseudonimizadas e dimensões agregadas necessárias ao projeto.",
            "- uploads manuais em plataforma devem usar preferencialmente o CSV da camada publicada.",
            "",
            "## Limitações e Escopo",
            "",
            "- o dataset Olist é público e anonimizado, mas o projeto adota privacidade por design para refletir prática corporativa.",
            "- esta camada não substitui controles organizacionais de acesso, mas reduz exposição desnecessária no produto analítico publicado.",
            "",
        ]
    )
    return "\n".join(lines)


def save_report(
    report: str,
    *,
    docs_dir: Path,
    report_path: Path,
    logger: logging.Logger,
) -> Path:
    ensure_directory(docs_dir)
    report_path.write_text(report, encoding="utf-8")
    logger.info("Documentação de privacidade salva em %s", report_path)
    return report_path
