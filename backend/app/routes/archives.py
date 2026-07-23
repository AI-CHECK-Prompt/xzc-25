"""档案归档、城建接口报送。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..config import get_settings
from ..db import get_db
from ..models import (
    ArchivePackage,
    ArchiveStatus,
    Component,
    PartyRole,
    Project,
    User,
)
from ..schemas import ArchiveOut
from ..services import generate_archive

router = APIRouter(prefix="/api/archives", tags=["档案归档"])

settings = get_settings()


@router.post("/generate/{component_id}", response_model=ArchiveOut, summary="生成电子档案包")
def generate(component_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(PartyRole.OWNER))):
    comp = db.get(Component, component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    archive = generate_archive(db, comp, user)
    db.commit()
    db.refresh(archive)
    return ArchiveOut.model_validate(archive)


@router.get("", response_model=List[ArchiveOut], summary="档案列表")
def list_archives(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.OWNER, PartyRole.QUALITY, PartyRole.SUPERVISOR)),
):
    q = db.query(ArchivePackage)
    if project_id:
        q = q.filter(ArchivePackage.project_id == project_id)
    return [ArchiveOut.model_validate(a) for a in q.order_by(ArchivePackage.id.desc()).all()]


@router.get("/{archive_id}/download", summary="下载电子档案包（ZIP）")
def download(archive_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(PartyRole.OWNER, PartyRole.QUALITY, PartyRole.SUPERVISOR))):
    archive = db.get(ArchivePackage, archive_id)
    if not archive or not os.path.exists(archive.file_path):
        raise HTTPException(status_code=404, detail="档案文件不存在")
    return FileResponse(
        archive.file_path,
        media_type="application/zip",
        filename=os.path.basename(archive.file_path),
    )


@router.post("/{archive_id}/submit", summary="通过接口报送至质量监督机构")
def submit(
    archive_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.OWNER)),
):
    archive = db.get(ArchivePackage, archive_id)
    if not archive:
        raise HTTPException(status_code=404, detail="档案不存在")
    if archive.status not in (ArchiveStatus.GENERATED, ArchiveStatus.REJECTED):
        raise HTTPException(status_code=409, detail=f"当前状态 {archive.status.value} 不允许重复报送")

    payload = {
        "archive_no": archive.archive_no,
        "component_trace_code": db.get(Component, archive.component_id).trace_code,
        "project": db.get(Project, archive.project_id).name if db.get(Project, archive.project_id) else "",
        "submitter": user.full_name,
        "submitted_at": datetime.now().isoformat(),
        "manifest": archive.payload,
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(settings.quality_supervision_endpoint, json=payload)
        ok = 200 <= resp.status_code < 300
    except Exception as exc:  # noqa: BLE001
        ok = False
        resp_status = str(exc)
    else:
        resp_status = resp.status_code

    archive.status = ArchiveStatus.SUBMITTED if ok else ArchiveStatus.REJECTED
    archive.submitted_at = datetime.now()
    db.commit()
    db.refresh(archive)
    return {
        "ok": ok,
        "remote_status": resp_status,
        "archive": ArchiveOut.model_validate(archive).model_dump(mode="json"),
    }
