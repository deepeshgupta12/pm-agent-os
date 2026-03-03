from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import (
    User,
    Workspace,
    Schedule,
    ScheduleRun,
)

# Reuse existing "create run" behavior (sync execution)
from app.api.runs import create_run as create_run_route
from app.api.pipelines import start_pipeline_run as start_pipeline_run_route

from app.schemas.core import RunCreateIn
from app.schemas.schedules import (
    ScheduleCreateIn,
    ScheduleUpdateIn,
    ScheduleOut,
    ScheduleRunOut,
    ScheduleRunNowOut,
    ScheduleRunDueOut,
)

router = APIRouter(tags=["schedules"])

VALID_KIND = {"agent_run", "pipeline_run"}


# -------------------------
# Time helpers
# -------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(id_str: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail=f"{label} not found")


def _as_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


# -------------------------
# FIX: make weekday convention explicit + UI-safe
# -------------------------
# We store weekdays as Python's weekday(): Monday=0 .. Sunday=6.
# This is ISO-ish and matches datetime.weekday().
# UI must NOT display "0=Sun"; it should map 0->Mon, ..., 6->Sun.
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _normalize_interval_json(interval_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Supported shapes:

    Daily:
    {
      "mode": "daily",
      "at": "HH:MM"
    }

    Weekly:
    {
      "mode": "weekly",
      "at": "HH:MM",
      "weekdays": [0..6]   # Monday=0 .. Sunday=6 (matches datetime.weekday)
    }

    Defaults:
    mode=daily, at=09:00
    """
    ij = interval_json or {}
    if not isinstance(ij, dict):
        ij = {}

    mode = str(ij.get("mode") or "daily").strip().lower()
    if mode not in {"daily", "weekly"}:
        mode = "daily"

    at = str(ij.get("at") or "09:00").strip()
    if ":" not in at:
        at = "09:00"
    hh_s, mm_s = (at.split(":", 1) + ["0"])[:2]
    try:
        hh = max(0, min(23, int(hh_s)))
        mm = max(0, min(59, int(mm_s)))
    except Exception:
        hh, mm = 9, 0
    at_norm = f"{hh:02d}:{mm:02d}"

    weekdays = ij.get("weekdays")
    if not isinstance(weekdays, list):
        weekdays = []
    wd_norm: List[int] = []
    for w in weekdays:
        try:
            x = int(w)
            if 0 <= x <= 6:
                wd_norm.append(x)
        except Exception:
            continue
    wd_norm = sorted(list(set(wd_norm)))

    out: Dict[str, Any] = {"mode": mode, "at": at_norm}
    if mode == "weekly":
        out["weekdays"] = wd_norm or [0]  # default Monday
    return out


def _compute_next_run_at(
    *,
    now_utc: datetime,
    tz_name: str,
    interval_json: Dict[str, Any],
) -> datetime:
    """
    Returns next run timestamp in UTC.
    Schedules are computed in schedule.timezone.

    Weekly convention: weekdays are Monday=0 .. Sunday=6 (datetime.weekday()).
    """
    tz = _as_zone(tz_name)
    now_local = now_utc.astimezone(tz)

    ij = _normalize_interval_json(interval_json)
    mode = ij["mode"]
    at = ij["at"]
    hh, mm = [int(x) for x in at.split(":")]

    def local_dt(d: datetime, hh_: int, mm_: int) -> datetime:
        return d.replace(hour=hh_, minute=mm_, second=0, microsecond=0)

    if mode == "daily":
        candidate = local_dt(now_local, hh, mm)
        if candidate <= now_local:
            candidate = local_dt(now_local + timedelta(days=1), hh, mm)
        return candidate.astimezone(timezone.utc)

    # weekly
    weekdays: List[int] = list(ij.get("weekdays") or [0])
    # python weekday: Monday=0..Sunday=6 matches our convention
    today_wd = int(now_local.weekday())
    _ = today_wd  # keep for readability / future debug

    # try today then next 6 days
    for delta_days in range(0, 7):
        d = now_local + timedelta(days=delta_days)
        if int(d.weekday()) not in weekdays:
            continue
        candidate = local_dt(d, hh, mm)
        if candidate > now_local:
            return candidate.astimezone(timezone.utc)

    # fallback: next week same time (safe)
    d2 = now_local + timedelta(days=7)
    candidate2 = local_dt(d2, hh, mm)
    return candidate2.astimezone(timezone.utc)


# -------------------------
# Mapping
# -------------------------
def _to_out(s: Schedule) -> ScheduleOut:
    return ScheduleOut(
        id=str(s.id),
        workspace_id=str(s.workspace_id),
        created_by_user_id=str(s.created_by_user_id) if s.created_by_user_id else None,
        name=s.name,
        kind=s.kind,
        timezone=s.timezone,
        cron=s.cron,
        interval_json=s.interval_json or {},
        payload_json=s.payload_json or {},
        enabled=bool(s.enabled),
        next_run_at=s.next_run_at,
        last_run_at=s.last_run_at,
        last_status=s.last_status,
        last_error=s.last_error,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _run_to_out(r: ScheduleRun) -> ScheduleRunOut:
    return ScheduleRunOut(
        id=str(r.id),
        schedule_id=str(r.schedule_id),
        status=r.status,
        started_at=r.started_at,
        finished_at=r.finished_at,
        error=r.error,
        run_id=str(r.run_id) if r.run_id else None,
        pipeline_run_id=str(r.pipeline_run_id) if r.pipeline_run_id else None,
        meta=r.meta or {},
    )


# -------------------------
# Routes
# -------------------------
@router.get("/workspaces/{workspace_id}/schedules", response_model=list[ScheduleOut])
def list_schedules(
    workspace_id: str,
    enabled: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    q = select(Schedule).where(Schedule.workspace_id == ws.id)
    if enabled is not None:
        q = q.where(Schedule.enabled.is_(bool(enabled)))
    q = q.order_by(desc(Schedule.created_at))

    rows = db.execute(q).scalars().all()
    return [_to_out(x) for x in rows]


@router.post("/workspaces/{workspace_id}/schedules", response_model=ScheduleOut)
def create_schedule(
    workspace_id: str,
    payload: ScheduleCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    kind = (payload.kind or "").strip().lower()
    if kind not in VALID_KIND:
        raise HTTPException(status_code=400, detail="Invalid schedule kind")

    tz_name = (payload.timezone or "UTC").strip() or "UTC"
    interval_json = payload.interval_json or {}
    norm_ij = _normalize_interval_json(interval_json)
    next_run_at = _compute_next_run_at(now_utc=_utcnow(), tz_name=tz_name, interval_json=norm_ij)

    s = Schedule(
        workspace_id=ws.id,
        created_by_user_id=user.id,
        name=payload.name.strip(),
        kind=kind,
        timezone=tz_name,
        cron=(payload.cron.strip() if payload.cron else None),
        interval_json=norm_ij,
        payload_json=payload.payload_json or {},
        enabled=bool(payload.enabled),
        next_run_at=next_run_at if payload.enabled else None,
        last_run_at=None,
        last_status=None,
        last_error=None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    sid = _parse_uuid(schedule_id, "Schedule")
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    require_workspace_access(str(s.workspace_id), db, user)
    return _to_out(s)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    sid = _parse_uuid(schedule_id, "Schedule")
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    ws, _role = require_workspace_role_min(str(s.workspace_id), "member", db, user)
    _ = ws  # explicit, not used beyond RBAC

    if payload.name is not None:
        s.name = payload.name.strip()

    if payload.enabled is not None:
        s.enabled = bool(payload.enabled)

    if payload.timezone is not None:
        s.timezone = (payload.timezone or "UTC").strip() or "UTC"

    if payload.cron is not None:
        s.cron = payload.cron.strip() if payload.cron else None

    if payload.interval_json is not None:
        s.interval_json = _normalize_interval_json(payload.interval_json or {})

    if payload.payload_json is not None:
        s.payload_json = payload.payload_json or {}

    # recompute next_run_at whenever schedule is enabled
    if s.enabled:
        s.next_run_at = _compute_next_run_at(
            now_utc=_utcnow(),
            tz_name=s.timezone,
            interval_json=s.interval_json or {},
        )
    else:
        s.next_run_at = None

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    sid = _parse_uuid(schedule_id, "Schedule")
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    require_workspace_role_min(str(s.workspace_id), "member", db, user)
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/schedules/{schedule_id}/runs", response_model=list[ScheduleRunOut])
def list_schedule_runs(
    schedule_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    sid = _parse_uuid(schedule_id, "Schedule")
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    require_workspace_access(str(s.workspace_id), db, user)

    rows = (
        db.execute(
            select(ScheduleRun)
            .where(ScheduleRun.schedule_id == s.id)
            .order_by(desc(ScheduleRun.started_at))
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_run_to_out(x) for x in rows]


def _execute_schedule_sync(
    *,
    db: Session,
    ws: Workspace,
    user: User,
    s: Schedule,
    reason: str,
) -> Tuple[ScheduleRun, Optional[str], Optional[str]]:
    """
    Returns (schedule_run, run_id, pipeline_run_id) as strings.
    Executes immediately (sync) inside API call.
    """
    sr = ScheduleRun(
        schedule_id=s.id,
        status="running",
        started_at=_utcnow(),
        finished_at=None,
        error=None,
        run_id=None,
        pipeline_run_id=None,
        meta={"reason": reason, "schedule_kind": s.kind, "payload_json": s.payload_json or {}},
    )
    db.add(sr)
    db.commit()
    db.refresh(sr)

    run_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None

    try:
        if (s.kind or "").lower() == "agent_run":
            pj = s.payload_json or {}
            agent_id = str(pj.get("agent_id") or "").strip()
            if not agent_id:
                raise Exception("schedule.payload_json.agent_id is required for agent_run")

            input_payload = pj.get("input_payload") or {}
            if not isinstance(input_payload, dict):
                raise Exception("schedule.payload_json.input_payload must be an object")

            retrieval = pj.get("retrieval")
            if retrieval is not None and not isinstance(retrieval, dict):
                raise Exception("schedule.payload_json.retrieval must be an object or null")

            rcfg = None
            if isinstance(retrieval, dict):
                rcfg = retrieval

            run_out = create_run_route(
                workspace_id=str(ws.id),
                payload=RunCreateIn(agent_id=agent_id, input_payload=input_payload, retrieval=rcfg),  # type: ignore[arg-type]
                db=db,
                user=user,
            )
            run_id = str(run_out.id)

            sr.run_id = uuid.UUID(run_id)
            sr.status = "success"

        elif (s.kind or "").lower() == "pipeline_run":
            pj = s.payload_json or {}
            template_id = str(pj.get("template_id") or "").strip()
            if not template_id:
                raise Exception("schedule.payload_json.template_id is required for pipeline_run")

            input_payload = pj.get("input_payload") or {}
            if not isinstance(input_payload, dict):
                raise Exception("schedule.payload_json.input_payload must be an object")

            from app.schemas.pipelines import PipelineRunCreateIn

            pr_out = start_pipeline_run_route(
                workspace_id=str(ws.id),
                payload=PipelineRunCreateIn(template_id=template_id, input_payload=input_payload),
                db=db,
                user=user,
            )
            pipeline_run_id = str(pr_out.id)

            sr.pipeline_run_id = uuid.UUID(pipeline_run_id)
            sr.status = "success"

        else:
            raise Exception("Invalid schedule kind")

        sr.finished_at = _utcnow()
        db.add(sr)

        # update schedule bookkeeping + next_run_at
        s.last_run_at = sr.finished_at
        s.last_status = sr.status
        s.last_error = None
        if s.enabled:
            s.next_run_at = _compute_next_run_at(
                now_utc=_utcnow(),
                tz_name=s.timezone,
                interval_json=s.interval_json or {},
            )
        db.add(s)

        db.commit()
        db.refresh(sr)
        return sr, run_id, pipeline_run_id

    except Exception as e:
        sr.status = "failed"
        sr.error = str(e)
        sr.finished_at = _utcnow()
        db.add(sr)

        s.last_run_at = sr.finished_at
        s.last_status = "failed"
        s.last_error = str(e)
        if s.enabled:
            s.next_run_at = _compute_next_run_at(
                now_utc=_utcnow(),
                tz_name=s.timezone,
                interval_json=s.interval_json or {},
            )
        db.add(s)

        db.commit()
        db.refresh(sr)
        return sr, None, None


@router.post("/schedules/{schedule_id}/run-now", response_model=ScheduleRunNowOut)
def run_schedule_now(
    schedule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    sid = _parse_uuid(schedule_id, "Schedule")
    s = db.get(Schedule, sid)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    ws, _role = require_workspace_role_min(str(s.workspace_id), "member", db, user)

    sr, run_id, pipeline_run_id = _execute_schedule_sync(db=db, ws=ws, user=user, s=s, reason="manual_run_now")

    return ScheduleRunNowOut(
        ok=True,
        schedule_id=str(s.id),
        schedule_run=_run_to_out(sr),
        run_id=run_id,
        pipeline_run_id=pipeline_run_id,
    )


@router.post("/workspaces/{workspace_id}/schedules/run-due", response_model=ScheduleRunDueOut)
def run_due_schedules(
    workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """
    Executes enabled schedules where next_run_at <= now (sync).
    Intended for "daily monitoring" / "weekly pack" manual trigger in V0.
    In V1/V2 we can wire this to a cron/worker.
    """
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    now = _utcnow()
    due = (
        db.execute(
            select(Schedule)
            .where(
                and_(
                    Schedule.workspace_id == ws.id,
                    Schedule.enabled.is_(True),
                    Schedule.next_run_at.is_not(None),
                    Schedule.next_run_at <= now,
                )
            )
            .order_by(Schedule.next_run_at.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    ran: List[ScheduleRunOut] = []
    for s in due:
        sr, _rid, _prid = _execute_schedule_sync(db=db, ws=ws, user=user, s=s, reason="run_due")
        ran.append(_run_to_out(sr))

    return ScheduleRunDueOut(
        ok=True,
        workspace_id=str(ws.id),
        due_count=len(due),
        executed_count=len(ran),
        schedule_runs=ran,
        now=now,
    )