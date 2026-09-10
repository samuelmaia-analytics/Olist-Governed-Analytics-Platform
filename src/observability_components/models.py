from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservabilityCheck:
    check_name: str
    status: str
    severity: str
    metric_value: float | str
    threshold: float | str
    details: str
