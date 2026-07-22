"""参与方、项目字典查询。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Party, Project, User
from ..schemas import PartyOut, ProjectOut

router = APIRouter(prefix="/api/meta", tags=["元数据"])


@router.get("/parties", response_model=List[PartyOut])
def list_parties(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [PartyOut.model_validate(p) for p in db.query(Party).order_by(Party.id).all()]


@router.get("/projects", response_model=List[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [ProjectOut.model_validate(p) for p in db.query(Project).order_by(Project.id).all()]
