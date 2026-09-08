from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MonitoringCheckResult:
    check_name: str
    status: str
    metric_value: float | str
    threshold: float | str
    severity: str
    details: str


@dataclass
class AlertDispatchResult:
    delivered: bool
    status_code: int | None
    destination: str
