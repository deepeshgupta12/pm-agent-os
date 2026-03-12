from __future__ import annotations

import csv
import io
from datetime import timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access
from app.core.governance import (
    policy_internal_only,
    audit_internal_only_check,
    policy_apply_pii_masking,
)
from app.db.session import get_db
from app.db.models import (
    Workspace,
    User,
    Run,
    Artifact,
    Evidence,
    GovernanceEvent,
    ActionItem,
)

router = APIRouter(tags=["audit_exports"])


def _iso(dt) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_exports_allowed(db: Session, ws: Workspace, user: User, *, action: str) -> None:
    """
    Enforce internal_only policy for ALL exports.
    Always audit allow/deny.
    """
    if policy_internal_only(ws):
        audit_internal_only_check(
            db,
            ws=ws,
            user=user,
            action=action,
            decision="deny",
            reason="Workspace is internal-only; exports are disabled.",
        )
        raise HTTPException(status_code=403, detail="Workspace is internal-only; exports are disabled.")

    audit_internal_only_check(
        db,
        ws=ws,
        user=user,
        action=action,
        decision="allow",
        reason="ok",
    )


def _csv_response(filename: str, rows: List[Dict[str, Any]]) -> Response:
    # Stable header union
    keys: List[str] = []
    seen = set()
    for r in rows:
        for k in (r or {}).keys():
            if k in seen:
                continue
            seen.add(k)
            keys.append(k)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in keys})

    data = buf.getvalue().encode("utf-8")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -------------------------
# Governance events exports
# -------------------------
@router.get("/workspaces/{workspace_id}/governance/events/export.json")
def export_governance_events_json(
    workspace_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    decision: Optional[str] = Query(default=None, description="allow|deny"),
    action_prefix: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.governance_events_json")

    q = select(GovernanceEvent).where(GovernanceEvent.workspace_id == ws.id)

    if decision:
        d = decision.strip().lower()
        if d not in {"allow", "deny"}:
            raise HTTPException(status_code=400, detail="Invalid decision (allow|deny)")
        q = q.where(GovernanceEvent.decision == d)

    if action_prefix:
        pref = action_prefix.strip()
        if pref:
            q = q.where(GovernanceEvent.action.like(f"{pref}%"))

    q = q.order_by(GovernanceEvent.created_at.desc()).limit(int(limit))
    rows = db.execute(q).scalars().all()

    items = [
        {
            "id": str(e.id),
            "workspace_id": str(e.workspace_id),
            "user_id": str(e.user_id) if e.user_id else None,
            "action": e.action,
            "decision": e.decision,
            "reason": e.reason or "",
            "meta": e.meta or {},
            "created_at": _iso(e.created_at),
        }
        for e in rows
    ]
    return {"workspace_id": str(ws.id), "items": items}


@router.get("/workspaces/{workspace_id}/governance/events/export.csv")
def export_governance_events_csv(
    workspace_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    decision: Optional[str] = Query(default=None, description="allow|deny"),
    action_prefix: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.governance_events_csv")

    payload = export_governance_events_json(
        workspace_id=workspace_id,
        limit=limit,
        decision=decision,
        action_prefix=action_prefix,
        db=db,
        user=user,
    )
    rows = []
    for it in payload.get("items", []):
        rows.append(
            {
                "id": it.get("id"),
                "workspace_id": it.get("workspace_id"),
                "user_id": it.get("user_id"),
                "action": it.get("action"),
                "decision": it.get("decision"),
                "reason": it.get("reason"),
                "created_at": it.get("created_at"),
                "meta_json": ("" if it.get("meta") is None else str(it.get("meta"))),
            }
        )
    return _csv_response("governance_events.csv", rows)


# -------------------------
# Workspace exports
# -------------------------
@router.get("/workspaces/{workspace_id}/exports/workspace.json")
def export_workspace_json(
    workspace_id: str,
    include_artifact_md: bool = Query(default=False, description="If true, include full artifact markdown"),
    limit_runs: int = Query(default=500, ge=1, le=5000),
    limit_events: int = Query(default=500, ge=1, le=5000),
    limit_actions: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.workspace_json")

    runs = db.execute(
        select(Run).where(Run.workspace_id == ws.id).order_by(Run.created_at.desc()).limit(int(limit_runs))
    ).scalars().all()

    run_ids = [r.id for r in runs]

    artifacts = []
    if run_ids:
        arts = db.execute(select(Artifact).where(Artifact.run_id.in_(run_ids)).order_by(Artifact.created_at.desc())).scalars().all()
        for a in arts:
            md = a.content_md or ""
            md_masked = policy_apply_pii_masking(ws, md, phase="export")
            artifacts.append(
                {
                    "id": str(a.id),
                    "run_id": str(a.run_id),
                    "type": a.type,
                    "title": a.title,
                    "logical_key": a.logical_key,
                    "version": int(a.version),
                    "status": a.status,
                    "assigned_to_user_id": str(a.assigned_to_user_id) if a.assigned_to_user_id else None,
                    "created_at": _iso(a.created_at),
                    "updated_at": _iso(a.updated_at),
                    "content_md": md_masked if include_artifact_md else None,
                }
            )

    evidence = []
    if run_ids:
        evs = db.execute(select(Evidence).where(Evidence.run_id.in_(run_ids)).order_by(Evidence.created_at.desc())).scalars().all()
        for e in evs:
            excerpt = policy_apply_pii_masking(ws, e.excerpt or "", phase="export")
            evidence.append(
                {
                    "id": str(e.id),
                    "run_id": str(e.run_id),
                    "kind": e.kind,
                    "source_name": e.source_name,
                    "source_ref": e.source_ref,
                    "excerpt": excerpt,
                    "meta": e.meta or {},
                    "created_at": _iso(e.created_at),
                }
            )

    events = db.execute(
        select(GovernanceEvent)
        .where(GovernanceEvent.workspace_id == ws.id)
        .order_by(GovernanceEvent.created_at.desc())
        .limit(int(limit_events))
    ).scalars().all()

    governance_events = [
        {
            "id": str(g.id),
            "workspace_id": str(g.workspace_id),
            "user_id": str(g.user_id) if g.user_id else None,
            "action": g.action,
            "decision": g.decision,
            "reason": g.reason or "",
            "meta": g.meta or {},
            "created_at": _iso(g.created_at),
        }
        for g in events
    ]

    actions = db.execute(
        select(ActionItem)
        .where(ActionItem.workspace_id == ws.id)
        .order_by(ActionItem.created_at.desc())
        .limit(int(limit_actions))
    ).scalars().all()

    action_items = [
        {
            "id": str(a.id),
            "workspace_id": str(a.workspace_id),
            "type": a.type,
            "status": a.status,
            "title": a.title,
            "target_ref": a.target_ref,
            "payload_json": a.payload_json or {},
            "approvals_required": int(getattr(a, "approvals_required", 1) or 1),
            "created_by_user_id": str(a.created_by_user_id),
            "assigned_to_user_id": str(a.assigned_to_user_id) if a.assigned_to_user_id else None,
            "decided_by_user_id": str(a.decided_by_user_id) if a.decided_by_user_id else None,
            "decided_at": _iso(a.decided_at) if a.decided_at else None,
            "decision_comment": a.decision_comment,
            "execution_status": getattr(a, "execution_status", "not_started"),
            "execution_attempts": int(getattr(a, "execution_attempts", 0) or 0),
            "execution_started_at": _iso(getattr(a, "execution_started_at", None)) if getattr(a, "execution_started_at", None) else None,
            "execution_finished_at": _iso(getattr(a, "execution_finished_at", None)) if getattr(a, "execution_finished_at", None) else None,
            "execution_last_error": getattr(a, "execution_last_error", None),
            "execution_idempotency_key": getattr(a, "execution_idempotency_key", None),
            "execution_result_json": getattr(a, "execution_result_json", {}) or {},
            "created_at": _iso(a.created_at),
            "updated_at": _iso(a.updated_at),
        }
        for a in actions
    ]

    runs_out = [
        {
            "id": str(r.id),
            "workspace_id": str(r.workspace_id),
            "agent_id": r.agent_id,
            "created_by_user_id": str(r.created_by_user_id),
            "status": r.status,
            "input_payload": r.input_payload or {},
            "output_summary": r.output_summary,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
        }
        for r in runs
    ]

    return {
        "workspace_id": str(ws.id),
        "exported_at": _iso(__import__("datetime").datetime.now(timezone.utc)),
        "runs": runs_out,
        "artifacts": artifacts,
        "evidence": evidence,
        "governance_events": governance_events,
        "action_items": action_items,
    }


@router.get("/workspaces/{workspace_id}/exports/runs.csv")
def export_runs_csv(
    workspace_id: str,
    limit: int = Query(default=2000, ge=1, le=20000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.runs_csv")

    rows_db = db.execute(
        select(Run).where(Run.workspace_id == ws.id).order_by(Run.created_at.desc()).limit(int(limit))
    ).scalars().all()

    rows = [
        {
            "id": str(r.id),
            "workspace_id": str(r.workspace_id),
            "agent_id": r.agent_id,
            "status": r.status,
            "created_by_user_id": str(r.created_by_user_id),
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
            "output_summary": r.output_summary or "",
            "input_payload_json": str(r.input_payload or {}),
        }
        for r in rows_db
    ]
    return _csv_response("runs.csv", rows)


@router.get("/workspaces/{workspace_id}/exports/artifacts.csv")
def export_artifacts_csv(
    workspace_id: str,
    include_content_md: bool = Query(default=False),
    limit: int = Query(default=5000, ge=1, le=20000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.artifacts_csv")

    run_ids = db.execute(select(Run.id).where(Run.workspace_id == ws.id)).scalars().all()
    if not run_ids:
        return _csv_response("artifacts.csv", [])

    arts = db.execute(select(Artifact).where(Artifact.run_id.in_(run_ids)).order_by(Artifact.created_at.desc()).limit(int(limit))).scalars().all()

    out = []
    for a in arts:
        md = a.content_md or ""
        md_masked = policy_apply_pii_masking(ws, md, phase="export")
        out.append(
            {
                "id": str(a.id),
                "run_id": str(a.run_id),
                "type": a.type,
                "title": a.title,
                "logical_key": a.logical_key,
                "version": int(a.version),
                "status": a.status,
                "assigned_to_user_id": str(a.assigned_to_user_id) if a.assigned_to_user_id else "",
                "created_at": _iso(a.created_at),
                "updated_at": _iso(a.updated_at),
                "content_md": md_masked if include_content_md else "",
            }
        )
    return _csv_response("artifacts.csv", out)


@router.get("/workspaces/{workspace_id}/exports/evidence.csv")
def export_evidence_csv(
    workspace_id: str,
    limit: int = Query(default=20000, ge=1, le=200000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.evidence_csv")

    run_ids = db.execute(select(Run.id).where(Run.workspace_id == ws.id)).scalars().all()
    if not run_ids:
        return _csv_response("evidence.csv", [])

    evs = db.execute(select(Evidence).where(Evidence.run_id.in_(run_ids)).order_by(Evidence.created_at.desc()).limit(int(limit))).scalars().all()

    out = []
    for e in evs:
        excerpt = policy_apply_pii_masking(ws, e.excerpt or "", phase="export")
        out.append(
            {
                "id": str(e.id),
                "run_id": str(e.run_id),
                "kind": e.kind,
                "source_name": e.source_name,
                "source_ref": e.source_ref or "",
                "excerpt": excerpt,
                "created_at": _iso(e.created_at),
                "meta_json": str(e.meta or {}),
            }
        )
    return _csv_response("evidence.csv", out)


@router.get("/workspaces/{workspace_id}/exports/action-items.csv")
def export_action_items_csv(
    workspace_id: str,
    limit: int = Query(default=5000, ge=1, le=20000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.action_items_csv")

    rows_db = db.execute(
        select(ActionItem).where(ActionItem.workspace_id == ws.id).order_by(ActionItem.created_at.desc()).limit(int(limit))
    ).scalars().all()

    rows = [
        {
            "id": str(a.id),
            "workspace_id": str(a.workspace_id),
            "type": a.type,
            "status": a.status,
            "title": a.title,
            "target_ref": a.target_ref or "",
            "created_by_user_id": str(a.created_by_user_id),
            "assigned_to_user_id": str(a.assigned_to_user_id) if a.assigned_to_user_id else "",
            "decided_by_user_id": str(a.decided_by_user_id) if a.decided_by_user_id else "",
            "decided_at": _iso(a.decided_at) if a.decided_at else "",
            "approvals_required": int(getattr(a, "approvals_required", 1) or 1),
            "execution_status": getattr(a, "execution_status", "not_started"),
            "execution_attempts": int(getattr(a, "execution_attempts", 0) or 0),
            "execution_last_error": getattr(a, "execution_last_error", "") or "",
            "created_at": _iso(a.created_at),
            "updated_at": _iso(a.updated_at),
            "payload_json": str(a.payload_json or {}),
            "execution_result_json": str(getattr(a, "execution_result_json", {}) or {}),
        }
        for a in rows_db
    ]
    return _csv_response("action_items.csv", rows)


@router.get("/workspaces/{workspace_id}/exports/governance-events.csv")
def export_governance_events_csv_simple(
    workspace_id: str,
    limit: int = Query(default=20000, ge=1, le=200000),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    _ensure_exports_allowed(db, ws, user, action="policy.internal_only.exports.governance_events_csv_simple")

    rows_db = db.execute(
        select(GovernanceEvent).where(GovernanceEvent.workspace_id == ws.id).order_by(GovernanceEvent.created_at.desc()).limit(int(limit))
    ).scalars().all()

    rows = [
        {
            "id": str(e.id),
            "workspace_id": str(e.workspace_id),
            "user_id": str(e.user_id) if e.user_id else "",
            "action": e.action,
            "decision": e.decision,
            "reason": e.reason or "",
            "created_at": _iso(e.created_at),
            "meta_json": str(e.meta or {}),
        }
        for e in rows_db
    ]
    return _csv_response("governance_events.csv", rows)