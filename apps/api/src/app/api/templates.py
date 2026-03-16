from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_role_min
from app.db.models import (
    AgentTemplate,
    PipelineTemplate,
    PromptTemplate,
    TemplateLibrary,
    ToolTemplate,
    User,
    Workspace,
)
from app.db.session import get_db
from app.schemas.templates import (
    PipelineTemplateCreate,
    PipelineTemplateUpdate,
    TemplateBaseCreate,
    TemplateBaseUpdate,
    TemplateLibraryCreate,
    TemplateLibraryOut,
    TemplateLibraryUpdate,
    TemplateOut,
    TemplateSurface,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/templates", tags=["templates"])


def _require_template_admin(workspace_id: str, db: Session, user: User) -> Workspace:
    ws, _ = require_workspace_role_min(workspace_id, "admin", db, user)
    return ws


def _library_scope_filter(
    *,
    ws_id: uuid.UUID,
    include_system: bool,
    library_id: Optional[uuid.UUID],
    surface: TemplateSurface,
):
    """
    Visibility rules:
    - Direct workspace-owned templates: workspace_id == ws_id
    - Library templates:
        - workspace libraries: library.workspace_id == ws_id
        - system libraries: library.workspace_id is NULL and library.is_system == True
    """
    if library_id is not None:
        return TemplateLibrary.id == library_id

    visibility = [TemplateLibrary.workspace_id == ws_id]
    if include_system:
        visibility.append(and_(TemplateLibrary.workspace_id.is_(None), TemplateLibrary.is_system.is_(True)))

    return and_(TemplateLibrary.surface == surface, or_(*visibility))


@router.get("/libraries", response_model=list[TemplateLibraryOut])
def list_template_libraries(
    workspace_id: str,
    surface: Optional[TemplateSurface] = Query(default=None),
    include_system: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _require_template_admin(workspace_id, db, user)

    filters = [
        or_(
            TemplateLibrary.workspace_id == ws.id,
            and_(TemplateLibrary.workspace_id.is_(None), TemplateLibrary.is_system.is_(True)),
        )
    ]
    if not include_system:
        filters = [TemplateLibrary.workspace_id == ws.id]
    if surface is not None:
        filters.append(TemplateLibrary.surface == surface)

    libs = (
        db.execute(select(TemplateLibrary).where(and_(*filters)).order_by(TemplateLibrary.created_at.desc()))
        .scalars()
        .all()
    )
    return libs


@router.post("/libraries", response_model=TemplateLibraryOut)
def create_template_library(
    workspace_id: str,
    payload: TemplateLibraryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _require_template_admin(workspace_id, db, user)

    if payload.is_system:
        raise HTTPException(status_code=403, detail="System libraries cannot be created via API")

    lib = TemplateLibrary(
        workspace_id=ws.id,
        surface=payload.surface,
        name=payload.name,
        description=payload.description,
        is_system=False,
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


@router.get("/libraries/{library_id}", response_model=TemplateLibraryOut)
def get_template_library(
    workspace_id: str,
    library_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _require_template_admin(workspace_id, db, user)

    lib = db.get(TemplateLibrary, library_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Template library not found")

    if lib.workspace_id not in (None, ws.id):
        raise HTTPException(status_code=403, detail="Template library not accessible")
    if lib.workspace_id is None and not lib.is_system:
        raise HTTPException(status_code=403, detail="Template library not accessible")
    return lib


@router.patch("/libraries/{library_id}", response_model=TemplateLibraryOut)
def update_template_library(
    workspace_id: str,
    library_id: uuid.UUID,
    payload: TemplateLibraryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _require_template_admin(workspace_id, db, user)

    lib = db.get(TemplateLibrary, library_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Template library not found")
    if lib.workspace_id != ws.id:
        raise HTTPException(status_code=403, detail="Only workspace libraries can be modified")

    if payload.name is not None:
        lib.name = payload.name
    if payload.description is not None:
        lib.description = payload.description

    db.commit()
    db.refresh(lib)
    return lib


@router.delete("/libraries/{library_id}")
def delete_template_library(
    workspace_id: str,
    library_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _require_template_admin(workspace_id, db, user)

    lib = db.get(TemplateLibrary, library_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Template library not found")
    if lib.workspace_id != ws.id:
        raise HTTPException(status_code=403, detail="Only workspace libraries can be deleted")

    db.delete(lib)
    db.commit()
    return {"ok": True}


def _validate_library_visibility(db: Session, ws_id: uuid.UUID, library_id: uuid.UUID, surface: TemplateSurface) -> TemplateLibrary:
    lib = db.get(TemplateLibrary, library_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Template library not found")
    if lib.surface != surface:
        raise HTTPException(status_code=400, detail="Template library surface mismatch")
    if lib.workspace_id == ws_id:
        return lib
    if lib.workspace_id is None and lib.is_system:
        return lib
    raise HTTPException(status_code=403, detail="Template library not accessible")


def _list_surface_templates(
    *,
    db: Session,
    ws_id: uuid.UUID,
    model,
    surface: TemplateSurface,
    include_system: bool,
    library_id: Optional[uuid.UUID],
):
    own = select(model).where(model.workspace_id == ws_id)

    lib_filters = _library_scope_filter(
        ws_id=ws_id, include_system=include_system, library_id=library_id, surface=surface
    )
    libs = (
        select(model)
        .join(TemplateLibrary, model.library_id == TemplateLibrary.id)
        .where(lib_filters)
    )

    rows = db.execute(own.union_all(libs)).scalars().all()
    if rows and hasattr(rows[0], "created_at"):
        rows.sort(key=lambda r: getattr(r, "created_at"), reverse=True)
    return rows


def _get_surface_template(
    *, db: Session, ws_id: uuid.UUID, model, surface: TemplateSurface, template_id: uuid.UUID, include_system: bool
):
    obj = db.get(model, template_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")

    if getattr(obj, "workspace_id") == ws_id:
        return obj

    lib_id = getattr(obj, "library_id")
    if lib_id is None:
        raise HTTPException(status_code=403, detail="Template not accessible")

    lib = db.get(TemplateLibrary, lib_id)
    if not lib or lib.surface != surface:
        raise HTTPException(status_code=403, detail="Template not accessible")

    if lib.workspace_id == ws_id:
        return obj
    if include_system and lib.workspace_id is None and lib.is_system:
        return obj

    raise HTTPException(status_code=403, detail="Template not accessible")


def _create_surface_template(
    *,
    db: Session,
    ws_id: uuid.UUID,
    model,
    surface: TemplateSurface,
    payload: TemplateBaseCreate,
):
    if payload.library_id is not None:
        _validate_library_visibility(db, ws_id, payload.library_id, surface)
        obj = model(
            library_id=payload.library_id,
            workspace_id=None,
            name=payload.name,
            description=payload.description,
            spec=payload.spec,
        )
    else:
        obj = model(
            workspace_id=ws_id,
            library_id=None,
            name=payload.name,
            description=payload.description,
            spec=payload.spec,
        )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _update_surface_template(
    *,
    db: Session,
    ws_id: uuid.UUID,
    model,
    surface: TemplateSurface,
    template_id: uuid.UUID,
    payload: TemplateBaseUpdate,
):
    obj = db.get(model, template_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")

    if getattr(obj, "workspace_id") != ws_id:
        raise HTTPException(status_code=403, detail="Only workspace-owned templates can be updated")

    if payload.name is not None:
        obj.name = payload.name
    if payload.description is not None:
        obj.description = payload.description
    if payload.spec is not None:
        obj.spec = payload.spec

    if payload.library_id is not None:
        lib = _validate_library_visibility(db, ws_id, payload.library_id, surface)
        if lib.workspace_id != ws_id:
            raise HTTPException(status_code=403, detail="Cannot move template into a system library")
        obj.library_id = payload.library_id
        obj.workspace_id = None

    db.commit()
    db.refresh(obj)
    return obj


def _delete_surface_template(*, db: Session, ws_id: uuid.UUID, model, template_id: uuid.UUID):
    obj = db.get(model, template_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")
    if getattr(obj, "workspace_id") != ws_id:
        raise HTTPException(status_code=403, detail="Only workspace-owned templates can be deleted")
    db.delete(obj)
    db.commit()
    return {"ok": True}


# -----------------
# Agent Templates
# -----------------

@router.get("/agents", response_model=list[TemplateOut])
def list_agent_templates(
    workspace_id: str,
    include_system: bool = Query(default=True),
    library_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    rows = _list_surface_templates(
        db=db,
        ws_id=ws.id,
        model=AgentTemplate,
        surface="agent",
        include_system=include_system,
        library_id=library_id,
    )
    return rows


@router.post("/agents", response_model=TemplateOut)
def create_agent_template(
    workspace_id: str,
    payload: TemplateBaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _create_surface_template(db=db, ws_id=ws.id, model=AgentTemplate, surface="agent", payload=payload)


@router.get("/agents/{template_id}", response_model=TemplateOut)
def get_agent_template(
    workspace_id: str,
    template_id: uuid.UUID,
    include_system: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    return _get_surface_template(
        db=db, ws_id=ws.id, model=AgentTemplate, surface="agent", template_id=template_id, include_system=include_system
    )


@router.patch("/agents/{template_id}", response_model=TemplateOut)
def update_agent_template(
    workspace_id: str,
    template_id: uuid.UUID,
    payload: TemplateBaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _update_surface_template(
        db=db, ws_id=ws.id, model=AgentTemplate, surface="agent", template_id=template_id, payload=payload
    )


@router.delete("/agents/{template_id}")
def delete_agent_template(
    workspace_id: str,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _delete_surface_template(db=db, ws_id=ws.id, model=AgentTemplate, template_id=template_id)


# -----------------
# Tool Templates
# -----------------

@router.get("/tools", response_model=list[TemplateOut])
def list_tool_templates(
    workspace_id: str,
    include_system: bool = Query(default=True),
    library_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    rows = _list_surface_templates(
        db=db,
        ws_id=ws.id,
        model=ToolTemplate,
        surface="tool",
        include_system=include_system,
        library_id=library_id,
    )
    return rows


@router.post("/tools", response_model=TemplateOut)
def create_tool_template(
    workspace_id: str,
    payload: TemplateBaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _create_surface_template(db=db, ws_id=ws.id, model=ToolTemplate, surface="tool", payload=payload)


@router.get("/tools/{template_id}", response_model=TemplateOut)
def get_tool_template(
    workspace_id: str,
    template_id: uuid.UUID,
    include_system: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    return _get_surface_template(
        db=db, ws_id=ws.id, model=ToolTemplate, surface="tool", template_id=template_id, include_system=include_system
    )


@router.patch("/tools/{template_id}", response_model=TemplateOut)
def update_tool_template(
    workspace_id: str,
    template_id: uuid.UUID,
    payload: TemplateBaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _update_surface_template(
        db=db, ws_id=ws.id, model=ToolTemplate, surface="tool", template_id=template_id, payload=payload
    )


@router.delete("/tools/{template_id}")
def delete_tool_template(
    workspace_id: str,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _delete_surface_template(db=db, ws_id=ws.id, model=ToolTemplate, template_id=template_id)


# -----------------
# Prompt Templates
# -----------------

@router.get("/prompts", response_model=list[TemplateOut])
def list_prompt_templates(
    workspace_id: str,
    include_system: bool = Query(default=True),
    library_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    rows = _list_surface_templates(
        db=db,
        ws_id=ws.id,
        model=PromptTemplate,
        surface="prompt",
        include_system=include_system,
        library_id=library_id,
    )
    return rows


@router.post("/prompts", response_model=TemplateOut)
def create_prompt_template(
    workspace_id: str,
    payload: TemplateBaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _create_surface_template(db=db, ws_id=ws.id, model=PromptTemplate, surface="prompt", payload=payload)


@router.get("/prompts/{template_id}", response_model=TemplateOut)
def get_prompt_template(
    workspace_id: str,
    template_id: uuid.UUID,
    include_system: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    return _get_surface_template(
        db=db, ws_id=ws.id, model=PromptTemplate, surface="prompt", template_id=template_id, include_system=include_system
    )


@router.patch("/prompts/{template_id}", response_model=TemplateOut)
def update_prompt_template(
    workspace_id: str,
    template_id: uuid.UUID,
    payload: TemplateBaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _update_surface_template(
        db=db, ws_id=ws.id, model=PromptTemplate, surface="prompt", template_id=template_id, payload=payload
    )


@router.delete("/prompts/{template_id}")
def delete_prompt_template(
    workspace_id: str,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)
    return _delete_surface_template(db=db, ws_id=ws.id, model=PromptTemplate, template_id=template_id)


# -----------------
# Pipeline Templates (library-aware, CRUD)
# -----------------

@router.get("/pipelines", response_model=list[Dict[str, Any]])
def list_pipeline_templates(
    workspace_id: str,
    include_system: bool = Query(default=True),
    library_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    rows = _list_surface_templates(
        db=db,
        ws_id=ws.id,
        model=PipelineTemplate,
        surface="pipeline",
        include_system=include_system,
        library_id=library_id,
    )

    out: list[Dict[str, Any]] = []
    for t in rows:
        out.append(
            {
                "id": str(t.id),
                "workspace_id": str(t.workspace_id) if t.workspace_id else None,
                "library_id": str(t.library_id) if t.library_id else None,
                "name": t.name,
                "description": t.description,
                "definition_json": t.definition_json,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
        )
    return out


@router.post("/pipelines", response_model=Dict[str, Any])
def create_pipeline_template(
    workspace_id: str,
    payload: PipelineTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)

    if payload.library_id is not None:
        _validate_library_visibility(db, ws.id, payload.library_id, "pipeline")
        obj = PipelineTemplate(
            library_id=payload.library_id,
            workspace_id=None,
            name=payload.name,
            description=payload.description,
            definition_json=payload.definition_json,
        )
    else:
        obj = PipelineTemplate(
            workspace_id=ws.id,
            library_id=None,
            name=payload.name,
            description=payload.description,
            definition_json=payload.definition_json,
        )

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {
        "id": str(obj.id),
        "workspace_id": str(obj.workspace_id) if obj.workspace_id else None,
        "library_id": str(obj.library_id) if obj.library_id else None,
        "name": obj.name,
        "description": obj.description,
        "definition_json": obj.definition_json,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


@router.get("/pipelines/{template_id}", response_model=Dict[str, Any])
def get_pipeline_template(
    workspace_id: str,
    template_id: uuid.UUID,
    include_system: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "viewer", db, user)
    obj = _get_surface_template(
        db=db,
        ws_id=ws.id,
        model=PipelineTemplate,
        surface="pipeline",
        template_id=template_id,
        include_system=include_system,
    )
    return {
        "id": str(obj.id),
        "workspace_id": str(obj.workspace_id) if obj.workspace_id else None,
        "library_id": str(obj.library_id) if obj.library_id else None,
        "name": obj.name,
        "description": obj.description,
        "definition_json": obj.definition_json,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


@router.patch("/pipelines/{template_id}", response_model=Dict[str, Any])
def update_pipeline_template(
    workspace_id: str,
    template_id: uuid.UUID,
    payload: PipelineTemplateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)

    obj = db.get(PipelineTemplate, template_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")
    if obj.workspace_id != ws.id:
        raise HTTPException(status_code=403, detail="Only workspace-owned templates can be updated")

    if payload.name is not None:
        obj.name = payload.name
    if payload.description is not None:
        obj.description = payload.description
    if payload.definition_json is not None:
        obj.definition_json = payload.definition_json

    if payload.library_id is not None:
        lib = _validate_library_visibility(db, ws.id, payload.library_id, "pipeline")
        if lib.workspace_id != ws.id:
            raise HTTPException(status_code=403, detail="Cannot move template into a system library")
        obj.library_id = payload.library_id
        obj.workspace_id = None

    db.commit()
    db.refresh(obj)
    return {
        "id": str(obj.id),
        "workspace_id": str(obj.workspace_id) if obj.workspace_id else None,
        "library_id": str(obj.library_id) if obj.library_id else None,
        "name": obj.name,
        "description": obj.description,
        "definition_json": obj.definition_json,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


@router.delete("/pipelines/{template_id}")
def delete_pipeline_template(
    workspace_id: str,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "member", db, user)

    obj = db.get(PipelineTemplate, template_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Template not found")
    if obj.workspace_id != ws.id:
        raise HTTPException(status_code=403, detail="Only workspace-owned templates can be deleted")

    db.delete(obj)
    db.commit()
    return {"ok": True}