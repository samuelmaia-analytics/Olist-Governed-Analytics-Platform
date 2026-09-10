from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityCheckResult:
    check_name: str
    status: str
    metric_value: float | str
    threshold: float | str
    severity: str
    details: str
