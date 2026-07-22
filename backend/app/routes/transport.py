"""运输遥测与告警。"""
from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..db import get_db
from ..models import (
    Component,
    FactoryOutRecord,
    PartyRole,
    TransportAlert,
    TransportTelemetry,
    User,
)
from ..schemas import AlertOut, TelemetryBatchIn, TelemetryIn
from ..services import detect_alerts

router = APIRouter(prefix="/api/transport", tags=["运输"])


@router.post("/telemetry", summary="上传单条车辆位置与温湿度")
def upload_telemetry(
    body: TelemetryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.TRANSPORT)),
):
    rec = db.get(FactoryOutRecord, body.transport_record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="出厂记录不存在")
    if rec.transport_party_id != user.party_id:
        raise HTTPException(status_code=403, detail="只能为本运输单位的构件上传轨迹")

    t = TransportTelemetry(
        component_id=body.component_id,
        transport_record_id=body.transport_record_id,
        reported_at=body.reported_at,
        longitude=body.longitude,
        latitude=body.latitude,
        temperature=body.temperature,
        humidity=body.humidity,
        status=body.status,
    )
    db.add(t)
    db.flush()
    detect_alerts(db, t)

    comp = db.get(Component, body.component_id)
    if comp and body.status.value in ("已到达", "已卸货"):
        comp.current_stage = "已到场"
    elif comp and body.status.value == "已装车":
        comp.current_stage = "运输中"
    db.commit()
    return {"ok": True, "telemetry_id": t.id}


@router.post("/telemetry/batch", summary="弱网恢复后批量回传运输遥测")
def upload_telemetry_batch(
    body: TelemetryBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.TRANSPORT)),
):
    accepted = 0
    rejected = 0
    for item in body.items:
        try:
            rec = db.get(FactoryOutRecord, item.transport_record_id)
            if not rec or rec.transport_party_id != user.party_id:
                rejected += 1
                continue
            t = TransportTelemetry(
                component_id=item.component_id,
                transport_record_id=item.transport_record_id,
                reported_at=item.reported_at,
                longitude=item.longitude,
                latitude=item.latitude,
                temperature=item.temperature,
                humidity=item.humidity,
                status=item.status,
            )
            db.add(t)
            db.flush()
            detect_alerts(db, t)
            accepted += 1
        except Exception:  # noqa: BLE001
            rejected += 1
    db.commit()
    return {"batch_id": body.batch_id, "accepted": accepted, "rejected": rejected}


@router.get("/alerts", response_model=List[AlertOut], summary="告警列表")
def list_alerts(
    component_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.OWNER, PartyRole.QUALITY, PartyRole.TRANSPORT, PartyRole.SUPERVISOR)),
):
    q = db.query(TransportAlert)
    if component_id:
        q = q.filter(TransportAlert.component_id == component_id)
    if user.role == PartyRole.TRANSPORT:
        # 运输单位只看与自己构件相关的告警
        from ..models import FactoryOutRecord as FOR
        rec = db.query(FOR.component_id).filter(FOR.transport_party_id == user.party_id).subquery()
        q = q.filter(TransportAlert.component_id.in_(rec))
    return [AlertOut.model_validate(a) for a in q.order_by(TransportAlert.created_at.desc()).all()]
