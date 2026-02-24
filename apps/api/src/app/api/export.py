from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.db.models import Artifact, Run, Workspace, User
from app.core.pdf_export import markdown_to_pdf_bytes

router = APIRouter(tags=["export"])


def _ensure_artifact_access(db: Session, art: Artifact, user: User) -> None:
    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    ws = db.get(Workspace, run.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Artifact not found")


@router.get("/artifacts/{artifact_id}/export/pdf")
def export_artifact_pdf(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    _ensure_artifact_access(db, art, user)

    pdf_bytes = markdown_to_pdf_bytes(title=art.title, markdown=art.content_md)
    filename = f"{art.logical_key}-v{art.version}.pdf".replace(" ", "_")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )