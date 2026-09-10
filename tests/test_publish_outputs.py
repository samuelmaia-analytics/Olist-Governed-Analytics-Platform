from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

from src.publish_components import outputs
from src.publish_components.models import PrivacyCheck, PublishedArtifacts

LOGGER = logging.getLogger(__name__)


def test_save_privacy_results_preserves_csv_schema(tmp_path: Path) -> None:
    result_path = tmp_path / "quality" / "privacy.csv"
    checks = [PrivacyCheck("required_columns", "PASS", "Ausentes: nenhuma")]

    returned = outputs.save_privacy_results(
        checks,
        quality_dir=result_path.parent,
        results_path=result_path,
        logger=LOGGER,
    )

    assert returned == result_path
    stored = pd.read_csv(result_path)
    assert stored.columns.tolist() == ["check_name", "status", "details"]
    assert stored.to_dict("records") == [
        {
            "check_name": "required_columns",
            "status": "PASS",
            "details": "Ausentes: nenhuma",
        }
    ]


def test_save_outputs_preserves_csv_parquet_and_artifact(tmp_path: Path) -> None:
    published_dir = tmp_path / "published"
    parquet_path = published_dir / "dashboard.parquet"
    csv_path = published_dir / "dashboard.csv"
    frame = pd.DataFrame({"order_id": ["order_1"], "price": [10.0]})

    artifacts = outputs.save_outputs(
        frame,
        published_dir=published_dir,
        parquet_path=parquet_path,
        csv_path=csv_path,
        logger=LOGGER,
    )

    assert artifacts == PublishedArtifacts(parquet_path, csv_path, 1, 2)
    pd.testing.assert_frame_equal(pd.read_parquet(parquet_path), frame)
    pd.testing.assert_frame_equal(pd.read_csv(csv_path), frame)


def test_render_and_save_report_preserve_utf8_and_paths(tmp_path: Path) -> None:
    artifacts = PublishedArtifacts(
        tmp_path / "dashboard.parquet", tmp_path / "dashboard.csv", 1, 34
    )
    checks = [PrivacyCheck("privacy", "PASS", "proteção aplicada")]
    report = outputs.render_report(
        artifacts,
        {"lgpd_principles": []},
        {"domain": "ecommerce", "version": 1},
        checks,
        removed_sensitive_columns=["customer_id"],
        published_parquet_path=artifacts.parquet_path,
        published_csv_path=artifacts.csv_path,
        privacy_results_path=tmp_path / "privacy.csv",
        to_relative_path_fn=lambda path: path.name,
    )
    report_path = tmp_path / "docs" / "privacy.md"

    returned = outputs.save_report(
        report, docs_dir=report_path.parent, report_path=report_path, logger=LOGGER
    )

    assert returned == report_path
    assert report_path.read_text(encoding="utf-8") == report
    assert "# Privacidade, LGPD e Governança" in report
    assert "proteção aplicada" in report
    assert "dashboard.parquet" in report


def test_output_persistence_errors_are_propagated(
    tmp_path: Path, monkeypatch
) -> None:
    frame = pd.DataFrame({"a": [1]})

    def fail_parquet(*args: object, **kwargs: object) -> None:
        raise OSError("parquet unavailable")

    monkeypatch.setattr(frame, "to_parquet", fail_parquet)
    with pytest.raises(OSError, match="parquet unavailable"):
        outputs.save_outputs(
            frame,
            published_dir=tmp_path,
            parquet_path=tmp_path / "x.parquet",
            csv_path=tmp_path / "x.csv",
            logger=LOGGER,
        )
