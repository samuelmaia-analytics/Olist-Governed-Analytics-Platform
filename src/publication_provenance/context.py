from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

import pandas as pd

from src.business_rule_components.models import BusinessRuleResult
from src.governance_types import PrivacyRiskResult
from src.monitoring_components.models import MonitoringCheckResult
from src.observability_components.models import ObservabilityCheck
from src.publication_evidence import (
    SensitiveDataProtectionResult,
    build_current_privacy_inputs,
    build_publication_evidence,
)
from src.publication_provenance.models import (
    EvidenceProvenance,
    EvidenceSource,
    ProvenancedPublicationEvidence,
)
from src.publish_components.models import PrivacyCheck
from src.quality_components.models import QualityCheckResult
from src.schema_contract_components.models import ContractCheck


@dataclass
class PipelineGovernanceContext:
    run_id: str
    started_at: datetime | None = None
    quality_results: tuple[QualityCheckResult, ...] | None = None
    schema_results: tuple[ContractCheck, ...] | None = None
    business_rule_results: tuple[BusinessRuleResult, ...] | None = None
    privacy_controls: tuple[PrivacyCheck, ...] | None = None
    privacy_risk_result: PrivacyRiskResult | Mapping[str, int] | None = None
    inherent_privacy_risk_score: int | None = None
    residual_privacy_risk_score: int | None = None
    inherent_privacy_risk_provenance: EvidenceProvenance | None = None
    residual_privacy_risk_provenance: EvidenceProvenance | None = None
    sensitive_data_protection: SensitiveDataProtectionResult | None = None
    classification_df: pd.DataFrame | None = None
    monitoring_results: tuple[MonitoringCheckResult, ...] | None = None
    observability_results: tuple[ObservabilityCheck, ...] | None = None
    provenance: dict[EvidenceSource, EvidenceProvenance] = field(default_factory=dict)

    def _record(
        self,
        source: EvidenceSource,
        *,
        produced_at: datetime | None,
        execution_step: str,
        dataset_name: str,
    ) -> None:
        self.provenance[source] = EvidenceProvenance(
            source=source,
            run_id=self.run_id,
            produced_at=produced_at,
            execution_step=execution_step,
            dataset_name=dataset_name,
        )

    def record_quality(
        self,
        results: list[QualityCheckResult],
        *,
        produced_at: datetime | None = None,
    ) -> None:
        self.quality_results = tuple(results)
        self._record(
            EvidenceSource.OPERATIONAL_QUALITY,
            produced_at=produced_at,
            execution_step="quality",
            dataset_name="fact_orders_enriched",
        )

    def record_schema(
        self,
        results: list[ContractCheck],
        *,
        produced_at: datetime | None = None,
    ) -> None:
        self.schema_results = tuple(results)
        self._record(
            EvidenceSource.SCHEMA_CONTRACTS,
            produced_at=produced_at,
            execution_step="contracts",
            dataset_name="multiple",
        )

    def record_business_rules(
        self,
        results: list[BusinessRuleResult],
        *,
        produced_at: datetime | None = None,
    ) -> None:
        self.business_rule_results = tuple(results)
        self._record(
            EvidenceSource.BUSINESS_RULES,
            produced_at=produced_at,
            execution_step="business_rules",
            dataset_name="fact_orders_enriched",
        )

    def record_privacy(
        self,
        results: list[PrivacyCheck],
        *,
        privacy_risk_result: PrivacyRiskResult | Mapping[str, int] | None = None,
        produced_at: datetime | None = None,
    ) -> None:
        self.privacy_controls = tuple(results)
        self.privacy_risk_result = privacy_risk_result
        score = privacy_risk_result.get("score") if privacy_risk_result else None
        self.inherent_privacy_risk_score = int(score) if score is not None else None
        self._record(
            EvidenceSource.PRIVACY,
            produced_at=produced_at,
            execution_step="publish",
            dataset_name="fact_orders_dashboard",
        )
        self.inherent_privacy_risk_provenance = self.provenance[
            EvidenceSource.PRIVACY
        ]

    def record_classification(
        self,
        classification_df: pd.DataFrame,
        *,
        produced_at: datetime | None = None,
    ) -> None:
        self.classification_df = classification_df.copy(deep=True)
        self._record(
            EvidenceSource.CLASSIFICATION,
            produced_at=produced_at,
            execution_step="classify",
            dataset_name="multiple",
        )

    def record_current_privacy(
        self,
        source_df: pd.DataFrame,
        published_df: pd.DataFrame,
        results: list[PrivacyCheck],
        *,
        produced_at: datetime | None = None,
        execution_step: str = "publish",
    ) -> None:
        current = build_current_privacy_inputs(source_df, published_df, results)
        self.privacy_controls = tuple(results)
        self.privacy_risk_result = current.risk_result
        self.inherent_privacy_risk_score = current.inherent_privacy_risk_score
        self.residual_privacy_risk_score = current.residual_privacy_risk_score
        self.sensitive_data_protection = current.protection
        if current.classification is not None:
            self.classification_df = current.classification.copy(deep=True)
        if current.risk_result is not None and current.protection.evaluated:
            self._record(
                EvidenceSource.PRIVACY,
                produced_at=produced_at,
                execution_step=execution_step,
                dataset_name="fact_orders_dashboard",
            )
            self.inherent_privacy_risk_provenance = self.provenance[
                EvidenceSource.PRIVACY
            ]
        if current.residual_privacy_risk_score is not None:
            self.residual_privacy_risk_provenance = EvidenceProvenance(
                source=EvidenceSource.PRIVACY,
                run_id=self.run_id,
                produced_at=produced_at,
                execution_step=execution_step,
                dataset_name="fact_orders_dashboard",
            )
        if current.classification is not None:
            self._record(
                EvidenceSource.CLASSIFICATION,
                produced_at=produced_at,
                execution_step=execution_step,
                dataset_name="fact_orders_enriched",
            )

    def record_monitoring(
        self,
        results: list[MonitoringCheckResult],
        *,
        produced_at: datetime | None = None,
    ) -> None:
        self.monitoring_results = tuple(results)
        self._record(
            EvidenceSource.MONITORING,
            produced_at=produced_at,
            execution_step="monitor",
            dataset_name="fact_orders_dashboard",
        )

    def record_observability(
        self,
        results: list[ObservabilityCheck],
        *,
        produced_at: datetime | None = None,
    ) -> None:
        self.observability_results = tuple(results)
        self._record(
            EvidenceSource.OBSERVABILITY,
            produced_at=produced_at,
            execution_step="monitor",
            dataset_name="fact_orders_dashboard",
        )

    def build_provenanced_evidence(self) -> ProvenancedPublicationEvidence:
        evidence = build_publication_evidence(
            quality_results=self.quality_results,
            schema_results=self.schema_results,
            business_rule_results=self.business_rule_results,
            privacy_controls=self.privacy_controls,
            privacy_risk_result=self.privacy_risk_result,
            classification_df=self.classification_df,
            sensitive_data_protection=self.sensitive_data_protection,
            monitoring_results=self.monitoring_results,
            observability_results=self.observability_results,
        )
        return ProvenancedPublicationEvidence(
            evidence=evidence,
            current_run_id=self.run_id,
            provenance=self.provenance,
        )
