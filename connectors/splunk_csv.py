"""Splunk CSV loader — Program 19905, dev/prod pipelines, 30-day window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import pandas as pd

import config

REQUIRED_PIPELINE_COLS = {
    "Deploy Start Time",
    "programId",
    "pipelineId",
    "pipelineName",
    "Execution",
    "Status",
}


class SplunkCsvError(Exception):
    pass


def _validate_columns(df: pd.DataFrame, path: str) -> None:
    missing = REQUIRED_PIPELINE_COLS - set(df.columns)
    if missing:
        raise SplunkCsvError(
            f"{path}: missing columns {sorted(missing)}. Found: {list(df.columns)}"
        )


def load_pipelines(csv_path: Optional[object] = None) -> pd.DataFrame:
    path = csv_path or config.SPLUNK_PIPELINES_CSV
    if not Path_exists(path):
        raise SplunkCsvError(f"Pipeline CSV not found: {path}")

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    _validate_columns(df, str(path))

    if "Execution" in df.columns:
        df = df.rename(columns={"Execution": "executionId"})
    elif "executionId" not in df.columns:
        raise SplunkCsvError(f"{path}: missing Execution/executionId column")
    df["executionId"] = df["executionId"].astype(str)
    df["programId"] = pd.to_numeric(df["programId"], errors="coerce")
    df["pipelineId"] = pd.to_numeric(df["pipelineId"], errors="coerce")
    df["Duration (Min)"] = pd.to_numeric(
        df.get("Duration (Min)", pd.Series(dtype=float)), errors="coerce"
    )

    df = df[df["programId"] == config.PROGRAM_ID]
    df = df[df["pipelineId"].isin([config.PIPELINE_ID_DEV, config.PIPELINE_ID_PROD])]

    if config.HISTORY_WINDOW_DAYS > 0:
        start_raw = df["Deploy Start Time"].astype(str).str.replace(
            r"\s+[A-Z]{2,4}$", "", regex=True
        )
        df["_start"] = pd.to_datetime(start_raw, errors="coerce", utc=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.HISTORY_WINDOW_DAYS)
        df = df[df["_start"] >= cutoff].copy()
        df.drop(columns=["_start"], inplace=True, errors="ignore")

    return df.reset_index(drop=True)


def Path_exists(path) -> bool:
    from pathlib import Path
    return Path(path).exists()


def load_failed_steps(csv_path: Optional[object] = None) -> pd.DataFrame:
    path = csv_path or config.SPLUNK_FAILED_STEPS_CSV
    if not Path_exists(path):
        raise SplunkCsvError(f"Failed steps CSV not found: {path}")

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    if "executionId" not in df.columns:
        raise SplunkCsvError(f"{path}: missing executionId column")
    df["executionId"] = df["executionId"].astype(str)
    df = df[df["executionId"].str.match(r"^\d+$", na=False)]
    return df


def load_share_names(csv_path: Optional[object] = None) -> Dict[str, str]:
    path = csv_path or config.SPLUNK_SHARE_NAMES_CSV
    if not Path_exists(path):
        raise SplunkCsvError(f"Share names CSV not found: {path}")

    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    df["executionId"] = df["executionId"].astype(str)
    df = df[df["executionId"].str.match(r"^\d+$", na=False)]
    df = df[df["shareName"].notna()]
    return dict(zip(df["executionId"], df["shareName"].astype(str)))


def split_dev_prod(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    dev = df[df["pipelineId"] == config.PIPELINE_ID_DEV].copy()
    prod = df[df["pipelineId"] == config.PIPELINE_ID_PROD].copy()
    return dev, prod


def get_execution_row(df: pd.DataFrame, execution_id: str) -> Optional[pd.Series]:
    rows = df[df["executionId"] == str(execution_id)]
    if rows.empty:
        return None
    return rows.iloc[0]
