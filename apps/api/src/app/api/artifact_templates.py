from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_user, require_workspace_role_min
from app.db import models
from app.db.models import Workspace

router = APIRouter(prefix="/workspaces/{workspace_id}/artifact-templates", tags=["artifact-templates"])


class ArtifactTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    definition_json: Dict[str, Any] = Field(default_factory=dict)


class ArtifactTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=20000)
    definition_json: Optional[Dict[str, Any]] = None


class ArtifactTemplateOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str
    definition_json: Dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    is_library: bool = False
    library_label: Optional[str] = None

    model_config = {"from_attributes": True}


def _library_refs_for_workspace(ws: Workspace) -> List[Dict[str, str]]:
    admin = ws.template_admin_json or {}
    libs = admin.get("template_libraries") or admin.get("libraries") or []
    out: List[Dict[str, str]] = []
    if not isinstance(libs, list):
        return out

    for x in libs:
        if not isinstance(x, dict):
            continue
        wid = str(x.get("workspace_id") or "").strip()
        if not wid:
            continue
        label = str(x.get("label") or "").strip() or "Library"
        out.append({"workspace_id": wid, "label": label})

    seen = set()
    uniq: List[Dict[str, str]] = []
    for r in out:
        wid = r["workspace_id"]
        if wid in seen:
            continue
        seen.add(wid)
        uniq.append(r)
    return uniq


def _allowed_template_workspace_ids(ws: Workspace) -> Tuple[List[uuid.UUID], Dict[str, str]]:
    allowed: List[uuid.UUID] = [ws.id]
    label_map: Dict[str, str] = {}

    for r in _library_refs_for_workspace(ws):
        try:
            wid = uuid.UUID(str(r["workspace_id"]))
        except Exception:
            continue
        if wid == ws.id:
            continue
        allowed.append(wid)
        label_map[str(wid)] = str(r.get("label") or "").strip() or "Library"

    seen = set()
    uniq: List[uuid.UUID] = []
    for wid in allowed:
        if wid in seen:
            continue
        seen.add(wid)
        uniq.append(wid)

    return uniq, label_map


def _resolve_artifact_template_or_404(
    db: Session, *, consumer_ws: Workspace, template_id: uuid.UUID
) -> Tuple[models.ArtifactTemplate, bool, Optional[str]]:
    t = db.get(models.ArtifactTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Artifact template not found")

    allowed_ids, label_map = _allowed_template_workspace_ids(consumer_ws)
    if t.workspace_id not in allowed_ids:
        raise HTTPException(status_code=404, detail="Artifact template not found")

    is_lib = str(t.workspace_id) != str(consumer_ws.id)
    lib_label = label_map.get(str(t.workspace_id)) if is_lib else None
    return t, is_lib, lib_label


@router.get("", response_model=List[ArtifactTemplateOut])
def list_artifact_templates(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_user),
) -> List[ArtifactTemplateOut]:
    consumer_ws, _role = require_workspace_role_min(str(workspace_id), "member", db, user)
    allowed_ids, label_map = _allowed_template_workspace_ids(consumer_ws)

    rows = (
        db.execute(
            select(models.ArtifactTemplate)
            .where(models.ArtifactTemplate.workspace_id.in_(allowed_ids))
            .order_by(models.ArtifactTemplate.updated_at.desc(), models.ArtifactTemplate.created_at.desc())
        )
        .scalars()
        .all()
    )

    out: List[ArtifactTemplateOut] = []
    for t in rows:
        is_lib = str(t.workspace_id) != str(consumer_ws.id)
        lib_label = label_map.get(str(t.workspace_id)) if is_lib else None
        out.append(
            ArtifactTemplateOut(
                id=t.id,
                workspace_id=t.workspace_id,
                name=t.name,
                description=t.description,
                definition_json=t.definition_json or {},
                created_at=t.created_at,
                updated_at=t.updated_at,
                is_library=is_lib,
                library_label=lib_label,
            )
        )
    return out


@router.get("/{template_id}", response_model=ArtifactTemplateOut)
def get_artifact_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_user),
) -> ArtifactTemplateOut:
    consumer_ws, _role = require_workspace_role_min(str(workspace_id), "member", db, user)
    t, is_lib, lib_label = _resolve_artifact_template_or_404(db, consumer_ws=consumer_ws, template_id=template_id)

    return ArtifactTemplateOut(
        id=t.id,
        workspace_id=t.workspace_id,
        name=t.name,
        description=t.description,
        definition_json=t.definition_json or {},
        created_at=t.created_at,
        updated_at=t.updated_at,
        is_library=is_lib,
        library_label=lib_label,
    )


@router.post("", response_model=ArtifactTemplateOut)
def create_artifact_template(
    workspace_id: uuid.UUID,
    payload: ArtifactTemplateCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_user),
) -> ArtifactTemplateOut:
    consumer_ws, _role = require_workspace_role_min(str(workspace_id), "member", db, user)

    t = models.ArtifactTemplate(
        workspace_id=consumer_ws.id,
        name=payload.name,
        description=payload.description,
        definition_json=payload.definition_json or {},
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    return ArtifactTemplateOut.model_validate(t)


@router.put("/{template_id}", response_model=ArtifactTemplateOut)
def update_artifact_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    payload: ArtifactTemplateUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_user),
) -> ArtifactTemplateOut:
    consumer_ws, _role = require_workspace_role_min(str(workspace_id), "member", db, user)
    t, is_lib, _lib_label = _resolve_artifact_template_or_404(db, consumer_ws=consumer_ws, template_id=template_id)

    if is_lib:
        raise HTTPException(status_code=403, detail="Cannot modify library template from this workspace")

    if payload.name is not None:
        t.name = payload.name
    if payload.description is not None:
        t.description = payload.description
    if payload.definition_json is not None:
        t.definition_json = payload.definition_json

    db.add(t)
    db.commit()
    db.refresh(t)
    return ArtifactTemplateOut.model_validate(t)


@router.delete("/{template_id}")
def delete_artifact_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_user),
) -> Dict[str, Any]:
    consumer_ws, _role = require_workspace_role_min(str(workspace_id), "member", db, user)
    t, is_lib, _lib_label = _resolve_artifact_template_or_404(db, consumer_ws=consumer_ws, template_id=template_id)

    if is_lib:
        raise HTTPException(status_code=403, detail="Cannot delete library template from this workspace")

    db.delete(t)
    db.commit()
    return {"ok": True}