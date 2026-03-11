# apps/api/src/app/api/evidence.py
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.evidence_store import evidence_fingerprint
from app.core.governance import (
    audit_policy_check,
    policy_allowed_source_types,
    policy_apply_pii_masking,
    policy_assert_allowed_sources,
)
from app.core.retrieval_search import hybrid_retrieve
from app.db.models import Evidence, Run, RunLog, User, Workspace
from app.db.session import get_db
from app.schemas.core import EvidenceCreateIn, EvidenceOut

router = APIRouter(tags=["evidence"])


def _enforce_policy_sources(db: Session, ws: Workspace, user: User, requested: Optional[List[str]], action: str) -> None:
    allowlist = policy_allowed_source_types(ws)
    try:
        policy_assert_allowed_sources(ws, requested)
        audit_policy_check(
            db,
            ws=ws,
            user=user,
            action=action,
            requested_source_types=requested or [],
            allowlist=allowlist,
            decision="allow",
            reason="ok",
        )
    except ValueError as e:
        audit_policy_check(
            db,
            ws=ws,
            user=user,
            action=action,
            requested_source_types=requested or [],
            allowlist=allowlist,
            decision="deny",
            reason=str(e),
        )
        raise HTTPException(status_code=403, detail=str(e))


class AutoEvidenceIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=6, ge=1, le=20)
    alpha: float = Field(default=0.65, ge=0.0, le=1.0)


# -------------------------
# V2.4: Attach preview as evidence
# -------------------------
class RetrievalPreviewCfgIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=50)
    alpha: float = Field(default=0.65, ge=0.0, le=1.0)

    # keep shape aligned with RunCreateIn retrieval
    source_types: List[str] = Field(default_factory=list)
    timeframe: Dict[str, Any] = Field(default_factory=dict)

    min_score: float = Field(default=0.15, ge=0.0, le=1.0)
    overfetch_k: int = Field(default=3, ge=1, le=10)
    rerank: bool = Field(default=False)


class PreviewItemIn(BaseModel):
    chunk_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=64)

    document_title: str = Field(default="", max_length=300)
    chunk_index: int = Field(default=0, ge=0)

    snippet: str = Field(default="")

    score_fts: float = Field(default=0.0)
    score_vec: float = Field(default=0.0)
    score_hybrid: float = Field(default=0.0)

    score_rerank_bonus: Optional[float] = None
    score_final: Optional[float] = None


class AttachPreviewEvidenceIn(BaseModel):
    retrieval: RetrievalPreviewCfgIn
    items: List[PreviewItemIn] = Field(default_factory=list, min_length=1, max_length=50)


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")


def _get_run_or_404(db: Session, run_id: str) -> Run:
    run_uuid = _parse_uuid(run_id)
    run = db.get(Run, run_uuid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _get_workspace_for_run(db: Session, run: Run) -> Workspace:
    ws = db.get(Workspace, run.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _to_uuid(v: Any) -> Optional[uuid.UUID]:
    try:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return uuid.UUID(s)
    except Exception:
        return None


def _evidence_to_out(e: Evidence) -> EvidenceOut:
    return EvidenceOut(
        id=str(e.id),
        run_id=str(e.run_id),
        kind=e.kind,
        source_name=e.source_name,
        source_ref=e.source_ref,
        excerpt=e.excerpt,
        meta=e.meta or {},
        fingerprint=getattr(e, "fingerprint", "") or "",
        source_id=str(getattr(e, "source_id", "") or "") or None,
        document_id=str(getattr(e, "document_id", "") or "") or None,
        chunk_id=str(getattr(e, "chunk_id", "") or "") or None,
    )


@router.post("/runs/{run_id}/evidence", response_model=EvidenceOut)
def add_evidence(
    run_id: str,
    payload: EvidenceCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run = _get_run_or_404(db, run_id)
    ws = _get_workspace_for_run(db, run)

    # member+ only
    require_workspace_role_min(str(run.workspace_id), "member", db, user)

    safe_excerpt = policy_apply_pii_masking(ws, payload.excerpt or "", phase="write")
    source_ref = (payload.source_ref or "").strip() or None

    fp = evidence_fingerprint(str(source_ref or ""), safe_excerpt)

    ev = Evidence(
        run_id=run.id,
        kind=payload.kind,
        source_name=payload.source_name,
        source_ref=source_ref,
        excerpt=safe_excerpt,
        meta=payload.meta or {},
        fingerprint=fp,
        source_id=_to_uuid((payload.meta or {}).get("source_id")),
        document_id=_to_uuid((payload.meta or {}).get("document_id")),
        chunk_id=_to_uuid((payload.meta or {}).get("chunk_id")),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    return _evidence_to_out(ev)


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run = _get_run_or_404(db, run_id)

    # viewer+ read ok
    require_workspace_access(str(run.workspace_id), db, user)

    items = (
        db.execute(select(Evidence).where(Evidence.run_id == run.id).order_by(Evidence.created_at.desc()))
        .scalars()
        .all()
    )
    return [_evidence_to_out(e) for e in items]


@router.post("/runs/{run_id}/evidence/auto", response_model=list[EvidenceOut])
def auto_add_evidence(
    run_id: str,
    payload: AutoEvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run = _get_run_or_404(db, run_id)
    ws = _get_workspace_for_run(db, run)

    # member+ only
    require_workspace_role_min(str(run.workspace_id), "member", db, user)

    _enforce_policy_sources(db, ws, user, None, "policy.allowlist.evidence.auto_add")

    items = hybrid_retrieve(
        db,
        workspace_id=str(run.workspace_id),
        q=payload.query,
        k=payload.k,
        alpha=payload.alpha,
    )
    if not items:
        return []

    created: list[Evidence] = []
    existing_fps = set(db.execute(select(Evidence.fingerprint).where(Evidence.run_id == run.id)).scalars().all())

    for rank, it in enumerate(items, start=1):
        doc_id = it.get("document_id")
        chunk_id = it.get("chunk_id")
        source_ref = f"doc:{doc_id}#chunk:{chunk_id}"

        excerpt_raw = str(it.get("snippet", "") or "")
        excerpt = policy_apply_pii_masking(ws, excerpt_raw, phase="write")

        fp = evidence_fingerprint(source_ref, excerpt)
        if fp in existing_fps:
            continue
        existing_fps.add(fp)

        meta = {
            "rank": rank,
            "score_hybrid": float(it.get("score_hybrid", 0.0)),
            "document_title": it.get("document_title", ""),
            "source_id": it.get("source_id", ""),
            "chunk_index": int(it.get("chunk_index", 0)),
        }

        ev = Evidence(
            run_id=run.id,
            kind="snippet",
            source_name="retrieval",
            source_ref=source_ref,
            excerpt=excerpt,
            meta=meta,
            fingerprint=fp,
            source_id=_to_uuid(it.get("source_id")),
            document_id=_to_uuid(doc_id),
            chunk_id=_to_uuid(chunk_id),
        )
        db.add(ev)
        created.append(ev)

    db.commit()
    for e in created:
        db.refresh(e)

    return [_evidence_to_out(e) for e in created]


# -------------------------
# V2.4: Attach preview results as evidence (member+)
# -------------------------
@router.post("/runs/{run_id}/evidence/attach-preview", response_model=list[EvidenceOut])
def attach_preview_as_evidence(
    run_id: str,
    payload: AttachPreviewEvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run = _get_run_or_404(db, run_id)
    ws = _get_workspace_for_run(db, run)

    # member+ only
    require_workspace_role_min(str(run.workspace_id), "member", db, user)

    if not payload.items:
        return []

    batch_id = str(uuid.uuid4())

    r = payload.retrieval
    retrieval_meta: Dict[str, Any] = {
        "enabled": True,
        "query": (r.query or "").strip(),
        "k": int(r.k),
        "alpha": float(r.alpha),
        "source_types": [s.strip().lower() for s in (r.source_types or []) if s and s.strip()],
        "timeframe": r.timeframe or {},
        "min_score": float(r.min_score),
        "overfetch_k": int(r.overfetch_k),
        "rerank": bool(r.rerank),
        "batch_kind": "preview_attach",
    }

    _enforce_policy_sources(
        db,
        ws,
        user,
        retrieval_meta.get("source_types") or None,
        "policy.allowlist.evidence.attach_preview",
    )

    created: List[Evidence] = []
    existing_fps = set(db.execute(select(Evidence.fingerprint).where(Evidence.run_id == run.id)).scalars().all())

    for rank, it in enumerate(payload.items, start=1):
        source_ref = f"doc:{it.document_id}#chunk:{it.chunk_id}"

        excerpt_raw = it.snippet or ""
        excerpt = policy_apply_pii_masking(ws, excerpt_raw, phase="write")

        fp = evidence_fingerprint(source_ref, excerpt)
        if fp in existing_fps:
            continue
        existing_fps.add(fp)

        meta = {
            "batch_id": batch_id,
            "batch_kind": "preview_attach",
            "rank": int(rank),
            "document_title": it.document_title or "",
            "source_id": it.source_id or "",
            "chunk_index": int(it.chunk_index or 0),
            "score_fts": float(it.score_fts or 0.0),
            "score_vec": float(it.score_vec or 0.0),
            "score_hybrid": float(it.score_hybrid or 0.0),
            "score_rerank_bonus": it.score_rerank_bonus,
            "score_final": it.score_final,
            "retrieval": retrieval_meta,
        }

        ev = Evidence(
            run_id=run.id,
            kind="snippet",
            source_name="retrieval",
            source_ref=source_ref,
            excerpt=excerpt,
            meta=meta,
            fingerprint=fp,
            source_id=_to_uuid(it.source_id),
            document_id=_to_uuid(it.document_id),
            chunk_id=_to_uuid(it.chunk_id),
        )
        db.add(ev)
        created.append(ev)

    db.commit()
    for e in created:
        db.refresh(e)

    db.add(
        RunLog(
            run_id=run.id,
            level="info",
            message="Preview evidence attached.",
            meta={
                "batch_id": batch_id,
                "batch_kind": "preview_attach",
                "evidence_count": len(created),
                "retrieval": retrieval_meta,
            },
        )
    )
    db.commit()

    return [_evidence_to_out(e) for e in created]