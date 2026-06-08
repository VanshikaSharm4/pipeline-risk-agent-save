"""Splunk REST export API — fetch pipeline executions (replaces manual CSV)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EXPORT_URL = os.getenv(
    "SPLUNK_EXPORT_URL",
    "https://splunk-api.or1.adobe.net:443/servicesNS/admin/TA-AMS_ui/search/jobs/export",
)
SPLUNK_EARLIEST = os.getenv("SPLUNK_EARLIEST", "-90d")
SPLUNK_LATEST = os.getenv("SPLUNK_LATEST", "now")


def _pipeline_search(program_id: int, pipeline_id: int) -> str:
    return f'''search index="ams_linux-os" sourcetype="ssg-summit-prod" TERM({program_id}) TERM({pipeline_id}) (CASE("pipeline_execution_start") OR CASE("pipeline_execution_end")) (logger_name="com.adobe.platform.experience.selfservice.services.AdobeIOEventService" OR logger_name="c.a.p.e.s.s.AdobeIOEventService")
| rex field=_raw "program/(?<programId>[0-9]+)/pipeline/(?<pipelineId>[0-9]+)/execution/(?<executionId>[0-9]+)"
| rex field=_raw "(?<hasEnded>PipelineExecutionEndedEvent)"
| search programId={program_id} pipelineId={pipeline_id}
| fields _time hasEnded, programId pipelineId executionId pipelineName status
| join type=left programId
    [ inputlookup "ams_ims_cmgr_customers.csv"
    | rename customerName as programName
    | fields programId, programName
    | table programId programName]
| where !isnull(pipelineId)
| stats values(*) as *, min(_time) as minStartedTime, max(_time) as maxEndTime min(status) as execStatus by executionId, pipelineId, programId
| eval pipelineInfo=if(isnull(pipelineName),pipelineId, mvjoin(mvindex(pipelineName,0),"") . " [".pipelineId."]")
| eval programInfo=if(isnull(programName),programId, mvjoin(mvindex(programName,0),"") . " [".programId."]")
| eval Status=if(isnull(execStatus) OR match(execStatus, "STARTED"), if(isnotnull(hasEnded), "ERROR", "RUNNING"), execStatus)
| eval searchTime = minStartedTime-259200
| eval searchEndTime = if(isnull(Status) OR match(Status, "RUNNING"), "now", maxEndTime+259200)
| eval startTime=strftime(minStartedTime, "%Y-%m-%dT%H:%M:%S.%Q %Z")
| eval endTime=strftime(maxEndTime, "%Y-%m-%dT%H:%M:%S.%Q %Z")
| eval difference=if(isnull(execStatus) OR match(execStatus, "STARTED"),  now() - minStartedTime, maxEndTime-minStartedTime)
| eval duration=round(difference/60,2)
| sort 0 -minStartedTime
| table startTime endTime searchTime searchEndTime duration programInfo programId pipelineInfo pipelineId executionId pipelineName Status
| rename startTime as "Deploy Start Time"
| rename endTime as "End Time"
| rename duration as "Duration (Min)"
| rename programInfo as "Program"
| rename pipelineInfo as "Pipeline"
| rename executionId as "Execution"'''


def _auth():
    user = os.getenv("SPLUNK_USERNAME", "")
    pwd = os.getenv("SPLUNK_PASSWORD", "")
    if not user or not pwd:
        raise ValueError("Set SPLUNK_USERNAME and SPLUNK_PASSWORD in .env")
    return user, pwd


def fetch_pipeline_export(pipeline_id: int, timeout: int = 300) -> pd.DataFrame:
    """Run Splunk export for one pipeline ID; returns DataFrame."""
    user, pwd = _auth()
    spl = _pipeline_search(config.PROGRAM_ID, pipeline_id)

    resp = requests.post(
        EXPORT_URL,
        auth=(user, pwd),
        data={
            "output_mode": "csv",
            "earliest_time": SPLUNK_EARLIEST,
            "latest_time": SPLUNK_LATEST,
            "search": spl,
        },
        verify=False,
        timeout=timeout,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "No results" in text:
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO(text))
    df.columns = df.columns.str.strip()
    if "Execution" in df.columns:
        df = df.rename(columns={"Execution": "executionId"})
    elif "executionId" not in df.columns and len(df.columns):
        pass
    return df


def fetch_execution_by_id(execution_id: str, timeout: int = 120) -> Optional[pd.DataFrame]:
    """Fetch a single execution row from Splunk by execution ID."""
    user, pwd = _auth()
    spl = (
        f'search index="ams_linux-os" sourcetype="ssg-summit-prod" TERM({execution_id})'
        f' (CASE("pipeline_execution_start") OR CASE("pipeline_execution_end"))'
        f' (logger_name="com.adobe.platform.experience.selfservice.services.AdobeIOEventService"'
        f' OR logger_name="c.a.p.e.s.s.AdobeIOEventService")'
        f'| rex field=_raw "program/(?P<programId>[0-9]+)/pipeline/(?P<pipelineId>[0-9]+)/execution/(?P<executionId>[0-9]+)"'
        f'| rex field=_raw "(?P<hasEnded>PipelineExecutionEndedEvent)"'
        f'| search executionId={execution_id}'
        f'| fields _time hasEnded programId pipelineId executionId pipelineName status'
        f'| stats values(*) as *, min(_time) as minStartedTime, max(_time) as maxEndTime'
        f'  min(status) as execStatus by executionId, pipelineId, programId'
        f'| eval Status=if(isnull(execStatus) OR match(execStatus, "STARTED"),'
        f'  if(isnotnull(hasEnded), "ERROR", "RUNNING"), execStatus)'
        f'| eval startTime=strftime(minStartedTime, "%Y-%m-%dT%H:%M:%S.%Q %Z")'
        f'| eval endTime=strftime(maxEndTime, "%Y-%m-%dT%H:%M:%S.%Q %Z")'
        f'| eval difference=if(isnull(execStatus) OR match(execStatus, "STARTED"),'
        f'  now() - minStartedTime, maxEndTime-minStartedTime)'
        f'| eval duration=round(difference/60,2)'
        f'| rename startTime as "Deploy Start Time" endTime as "End Time"'
        f'  duration as "Duration (Min)" executionId as "Execution"'
    )
    resp = requests.post(
        EXPORT_URL,
        auth=(user, pwd),
        data={"output_mode": "csv", "earliest_time": SPLUNK_EARLIEST,
              "latest_time": SPLUNK_LATEST, "search": spl},
        verify=False,
        timeout=timeout,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text or "No results" in text:
        return None
    df = pd.read_csv(io.StringIO(text))
    df.columns = df.columns.str.strip()
    if "Execution" in df.columns:
        df = df.rename(columns={"Execution": "executionId"})
    return df


def fetch_all_pipelines() -> pd.DataFrame:
    """Fetch dev + prod pipelines and merge."""
    frames = []
    for pid, label in [
        (config.PIPELINE_ID_DEV, "dev"),
        (config.PIPELINE_ID_PROD, "prod"),
    ]:
        df = fetch_pipeline_export(pid)
        if not df.empty:
            df["pipelineId"] = pid
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["executionId"], keep="first")
    return merged


def save_pipelines_csv(df: pd.DataFrame, path: Optional[Path] = None) -> Path:
    out = path or config.SPLUNK_PIPELINES_CSV
    out.parent.mkdir(parents=True, exist_ok=True)
    export = df.copy()
    if "executionId" in export.columns:
        export = export.rename(columns={"executionId": "Execution"})
    export.to_csv(out, index=False)
    return out
