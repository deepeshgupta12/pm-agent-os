from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScheduleCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=3, max_length=32)  # agent_run | pipeline_run

    timezone: str = Field(default="UTC", max_length=64)
    cron: Optional[str] = Field(default=None, max_length=120)

    interval_json: Dict[str, Any] = Field(default_factory=dict)
    payload_json: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True


class ScheduleUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    timezone: Optional[str] = Field(default=None, max_length=64)
    cron: Optional[str] = Field(default=None, max_length=120)

    interval_json: Optional[Dict[str, Any]] = None
    payload_json: Optional[Dict[str, Any]] = None

    enabled: Optional[bool] = None


class ScheduleOut(BaseModel):
    id: str
    workspace_id: str
    created_by_user_id: Optional[str] = None

    name: str
    kind: str

    timezone: str
    cron: Optional[str] = None
    interval_json: Dict[str, Any] = Field(default_factory=dict)
    payload_json: Dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True

    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class ScheduleRunOut(BaseModel):
    id: str
    schedule_id: str
    status: str  # running|success|failed
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    run_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ScheduleRunNowOut(BaseModel):
    ok: bool = True
    schedule_id: str
    schedule_run: ScheduleRunOut
    run_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None


class ScheduleRunDueOut(BaseModel):
    ok: bool = True
    workspace_id: str
    due_count: int
    executed_count: int
    schedule_runs: List[ScheduleRunOut] = Field(default_factory=list)
    now: datetime