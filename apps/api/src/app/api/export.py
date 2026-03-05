from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access
from app.db.session import get_db
from app.db.models import Artifact, Run, User, Workspace
from app.core.pdf_export import markdown_to_pdf_bytes
from app.core.docx_export import markdown_to_docx_bytes
from app.core.governance import policy_internal_only, audit_internal_only_check, policy_apply_pii_masking

router = APIRouter(tags=["export"])


def _get_run_and_workspace(db: Session, art: Artifact) -> tuple[Run, Workspace]:
    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")

    ws = db.get(Workspace, run.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return run, ws


def _ensure_artifact_access(db: Session, art: Artifact, user: User) -> Workspace:
    run, ws = _get_run_and_workspace(db, art)

    # viewer+ can export (unless policy forbids)
    require_workspace_access(str(run.workspace_id), db, user)

    # Policy: internal-only blocks export
    if policy_internal_only(ws):
        audit_internal_only_check(
            db,
            ws=ws,
            user=user,
            action="policy.internal_only.export",
            decision="deny",
            reason="Workspace is internal-only; exports are disabled.",
        )
        raise HTTPException(status_code=403, detail="Workspace is internal-only; exports are disabled.")

    audit_internal_only_check(
        db,
        ws=ws,
        user=user,
        action="policy.internal_only.export",
        decision="allow",
        reason="ok",
    )
    return ws


@router.get("/artifacts/{artifact_id}/export/pdf")
def export_artifact_pdf(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    ws = _ensure_artifact_access(db, art, user)

    content_md = art.content_md or ""
    # Policy: export-time PII masking
    content_md = policy_apply_pii_masking(ws, content_md, phase="export")

    pdf_bytes = markdown_to_pdf_bytes(title=art.title, markdown=content_md)
    filename = f"{art.logical_key}-v{art.version}.pdf".replace(" ", "_")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/artifacts/{artifact_id}/export/docx")
def export_artifact_docx(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    ws = _ensure_artifact_access(db, art, user)

    content_md = art.content_md or ""
    # Policy: export-time PII masking
    content_md = policy_apply_pii_masking(ws, content_md, phase="export")

    try:
        docx_bytes = markdown_to_docx_bytes(title=art.title or "Artifact", markdown=content_md)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {e}")

    filename = f"{art.logical_key}-v{art.version}.docx".replace(" ", "_")

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )