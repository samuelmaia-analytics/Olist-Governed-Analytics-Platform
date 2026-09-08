from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContractCheck:
    dataset_name: str
    layer: str
    check_name: str
    status: str
    details: str
