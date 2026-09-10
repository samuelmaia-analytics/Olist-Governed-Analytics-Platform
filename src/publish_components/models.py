from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class PublishedArtifacts:
    parquet_path: Path
    csv_path: Path
    rows: int
    columns: int


@dataclass(frozen=True)
class PrivacyCheck:
    check_name: str
    status: str
    details: str


@dataclass(frozen=True, eq=False)
class PrivacyPreflightResult:
    """Current-run privacy evaluation completed without publication writes."""

    source_df: pd.DataFrame
    published_candidate: pd.DataFrame
    contract: dict[str, object]
    policy: dict[str, object]
    checks: list[PrivacyCheck]

    @property
    def failed_checks(self) -> int:
        return sum(check.status.upper() == "FAIL" for check in self.checks)

    @property
    def blocked(self) -> bool:
        return self.failed_checks > 0
