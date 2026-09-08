from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessRuleResult:
    rule_id: str
    status: str
    severity: str
    failed_rows: int
    failure_pct: float
    details: str
