from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TrackScore(BaseModel):
    prob: float = 0.0
    risk: str = "Low"
    confidence: str = "low"
    drivers: List[str] = Field(default_factory=list)
    n_samples: int = 0
    extra: Dict[str, Any] = Field(default_factory=dict)


class DevProdPair(BaseModel):
    commit_sha: str
    dev_execution_id: str
    dev_status: str
    dev_failed_step: Optional[str] = None
    dev_log_signals: List[str] = Field(default_factory=list)
    dev_modules: List[str] = Field(default_factory=list)
    prod_execution_id: str
    prod_status: str
    prod_failed_step: Optional[str] = None
    prod_log_signals: List[str] = Field(default_factory=list)
    label: str = ""
    pair_confidence: str = "medium"
    prod_failed_after_dev_pass: bool = False


class ProdRiskReport(BaseModel):
    dev_execution_id: str
    commit_sha: Optional[str] = None
    structured: TrackScore
    vector: Optional[TrackScore] = None
    combined: Optional[TrackScore] = None
    agreement: bool = True
    combination_note: str = ""
    recommendation: str = ""
    markdown: str = ""
