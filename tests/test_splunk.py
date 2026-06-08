"""Tests for Splunk CSV loader — no Azure/git required."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from connectors import splunk_csv


@pytest.fixture
def csv_dir(tmp_path):
    src = config.SPLUNK_PIPELINES_CSV.parent
    if not config.SPLUNK_PIPELINES_CSV.exists():
        pytest.skip("Splunk CSVs not present — copy to data/splunk_exports/")
    return src


def test_load_pipelines_filters_program_and_pipelines(csv_dir):
    df = splunk_csv.load_pipelines()
    assert (df["programId"] == config.PROGRAM_ID).all()
    assert set(df["pipelineId"].unique()).issubset(
        {config.PIPELINE_ID_DEV, config.PIPELINE_ID_PROD}
    )


def test_split_dev_prod(csv_dir):
    df = splunk_csv.load_pipelines()
    dev, prod = splunk_csv.split_dev_prod(df)
    assert (dev["pipelineId"] == config.PIPELINE_ID_DEV).all()
    assert (prod["pipelineId"] == config.PIPELINE_ID_PROD).all()


def test_share_names_dict(csv_dir):
    if not config.SPLUNK_SHARE_NAMES_CSV.exists():
        pytest.skip("share-names.csv missing")
    shares = splunk_csv.load_share_names()
    assert isinstance(shares, dict)
    assert len(shares) > 0
