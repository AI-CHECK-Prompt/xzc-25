"""构件追溯全链路查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..schemas import TraceResponse
from ..services import build_trace

router = APIRouter(prefix="/api/trace", tags=["追溯"])


@router.get("/{trace_code}", response_model=TraceResponse, summary="根据唯一追溯码查询全链路记录")
def get_trace(trace_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return build_trace(db, trace_code, user)
