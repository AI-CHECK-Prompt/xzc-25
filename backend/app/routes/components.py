"""构件生产、出厂管理。"""
from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..db import get_db
from ..models import (
    Component,
    FactoryOutRecord,
    Party,
    PartyRole,
    Project,
    User,
)
from ..schemas import (
    ComponentCreate,
    ComponentOut,
    FactoryOutCreate,
    FactoryOutOut,
)

router = APIRouter(prefix="/api/components", tags=["构件"])


def _generate_trace_code(db: Session, factory: Party) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"PC-{today}-{factory.code.upper()}"
    n = db.query(Component).filter(Component.trace_code.like(f"{prefix}-%")).count()
    return f"{prefix}-{n + 1:04d}"


@router.post("", response_model=ComponentOut, summary="工厂录入构件生产信息")
def create_component(
    body: ComponentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.FACTORY)),
):
    project = db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    factory = db.get(Party, user.party_id)
    if not factory:
        raise HTTPException(status_code=400, detail="用户未关联工厂参与方")

    comp = Component(
        project_id=body.project_id,
        factory_id=factory.id,
        component_type=body.component_type,
        spec=body.spec,
        quantity=body.quantity,
        mould_no=body.mould_no,
        rebar_batch=body.rebar_batch,
        concrete_ratio=body.concrete_ratio,
        pour_at=body.pour_at,
        curing_record=body.curing_record,
        strength_report=body.strength_report,
        embedded_parts=body.embedded_parts,
        factory_inspection=body.factory_inspection,
        current_stage="已生产",
    )
    comp.trace_code = _generate_trace_code(db, factory)
    comp.rfid_tag = f"RFID-{comp.trace_code}"
    comp.qr_payload = (
        f"http://localhost:5173/trace?code={comp.trace_code}"
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return ComponentOut.model_validate(comp)


@router.get("", response_model=List[ComponentOut], summary="查询构件列表（按项目与权限过滤）")
def list_components(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Component)
    if user.role == PartyRole.FACTORY:
        q = q.filter(Component.factory_id == user.party_id)
    elif user.role in (PartyRole.TRANSPORT, PartyRole.CONTRACTOR, PartyRole.SUPERVISOR):
        if project_id is None:
            return []
        q = q.filter(Component.project_id == project_id)
    if project_id:
        q = q.filter(Component.project_id == project_id)
    return [ComponentOut.model_validate(c) for c in q.order_by(Component.id.desc()).all()]


@router.get("/{trace_code}", summary="根据追溯码查询构件详情")
def get_component(trace_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    comp = db.query(Component).filter(Component.trace_code == trace_code).first()
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    return ComponentOut.model_validate(comp)


@router.post("/factory-out", response_model=FactoryOutOut, summary="构件出厂登记")
def factory_out(
    body: FactoryOutCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.FACTORY)),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    if comp.factory_id != user.party_id:
        raise HTTPException(status_code=403, detail="只能为本工厂构件登记出厂")

    transport = db.get(Party, body.transport_party_id)
    if not transport or transport.role != PartyRole.TRANSPORT:
        raise HTTPException(status_code=400, detail="运输单位无效")

    rec = FactoryOutRecord(
        component_id=comp.id,
        factory_id=comp.factory_id,
        transport_party_id=body.transport_party_id,
        out_at=body.out_at,
        vehicle_no=body.vehicle_no,
        driver=body.driver,
        driver_phone=body.driver_phone,
        route_plan=body.route_plan,
        inspection_conclusion=body.inspection_conclusion,
    )
    comp.current_stage = "运输中"
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return FactoryOutOut.model_validate(rec)
