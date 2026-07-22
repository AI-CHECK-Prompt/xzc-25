"""进场、吊装、节点连接、隐蔽验收、成品保护。

进场 → 吊装 → 节点连接 → 隐蔽验收 → 成品保护，构成施工现场的四道关键环节。
不合格件无法被吊装：核心校验。
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..db import get_db
from ..models import (
    AcceptanceResult,
    Component,
    ConcealedAcceptance,
    HoistingRecord,
    JointConnection,
    PartyRole,
    Project,
    ProtectionRecord,
    SiteEntryRecord,
    User,
)
from ..schemas import (
    ConcealedCreate,
    ConcealedOut,
    HoistingCreate,
    HoistingOut,
    JointCreate,
    JointOut,
    ProtectionCreate,
    ProtectionOut,
    SiteEntryCreate,
    SiteEntryOut,
)

router = APIRouter(prefix="/api/site", tags=["现场作业"])

log = logging.getLogger(__name__)


# ---------- 进场 ----------
@router.post("/entry", response_model=SiteEntryOut, summary="构件进场扫码登记")
def site_entry(
    body: SiteEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.CONTRACTOR)),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    rec = SiteEntryRecord(
        component_id=comp.id,
        contractor_id=user.party_id,
        entered_at=body.entered_at,
        stack_location=body.stack_location,
        inspector=body.inspector,
        acceptance=body.acceptance,
        remark=body.remark,
        photo_urls=body.photo_urls,
    )
    comp.current_stage = "已进场" if body.acceptance.value == "合格" else "进场不合格"
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return SiteEntryOut.model_validate(rec)


# ---------- 吊装 ----------
@router.get("/hoisting/eligible", summary="可吊装构件（自动过滤不合格件）")
def eligible_components(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.CONTRACTOR)),
):
    """返回当前账号所属项目下已进场且验收合格、未吊装的构件。

    修复说明：
      原实现直接对全平台 SiteEntryRecord / HoistingRecord 取集合，未按当前
      账号所属项目做隔离，会把其他工地的合格件一并返回，施工员扫码吊装时
      才在 HoistingRecord 写入阶段被 cross-project 校验拒收。改为先按
      Project.contractor_party_id 圈定本账号的项目白名单，再做合格/未吊装
      筛选，杜绝跨工地误显示。
    """
    # 1) 当前账号所属项目白名单（一个施工总承包可承接多个项目）
    project_ids = [
        p.id
        for p in db.query(Project.id)
        .filter(Project.contractor_party_id == user.party_id)
        .all()
    ]
    if not project_ids:
        log.info(
            "【现场作业-可吊装】账号无所属项目 user=%s party=%s",
            user.username, user.party_id,
        )
        return []

    # 2) 白名单项目下的全部构件
    project_component_ids = {
        c.id
        for c in db.query(Component.id)
        .filter(Component.project_id.in_(project_ids))
        .all()
    }
    if not project_component_ids:
        return []

    # 3) 进场验收合格件（限白名单项目）
    passed_ids = {
        r.component_id
        for r in db.query(SiteEntryRecord.component_id)
        .filter(
            SiteEntryRecord.acceptance == AcceptanceResult.PASSED,
            SiteEntryRecord.component_id.in_(project_component_ids),
        )
        .all()
    }
    if not passed_ids:
        return []

    # 4) 已吊装件（仅在白名单内求差集，避免被其他工地的吊装记录污染）
    hoisted_ids = {
        r.component_id
        for r in db.query(HoistingRecord.component_id)
        .filter(HoistingRecord.component_id.in_(passed_ids))
        .all()
    }

    comps = (
        db.query(Component)
        .filter(Component.id.in_(passed_ids))
        .order_by(Component.id.desc())
        .all()
    )
    log.info(
        "【现场作业-可吊装】user=%s projects=%s passed=%d hoisted=%d returned=%d",
        user.username, project_ids, len(passed_ids), len(hoisted_ids),
        sum(1 for c in comps if c.id not in hoisted_ids),
    )
    return [
        {
            "trace_code": c.trace_code,
            "spec": c.spec,
            "type": c.component_type.value,
            "current_stage": c.current_stage,
        }
        for c in comps
        if c.id not in hoisted_ids
    ]


@router.post("/hoisting", response_model=HoistingOut, summary="吊装登记（自动校验合格性）")
def hoist(
    body: HoistingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.CONTRACTOR)),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    site = (
        db.query(SiteEntryRecord).filter(SiteEntryRecord.component_id == comp.id).first()
    )
    if not site:
        raise HTTPException(status_code=400, detail="构件尚未进场登记")
    if site.acceptance.value != "合格":
        # 核心硬性要求：不合格件禁止吊装
        raise HTTPException(
            status_code=409,
            detail=f"构件进场验收结论为「{site.acceptance.value}」，禁止进入吊装流程",
        )
    if db.query(HoistingRecord).filter(HoistingRecord.component_id == comp.id).first():
        raise HTTPException(status_code=409, detail="该构件已吊装，禁止重复登记")

    rec = HoistingRecord(
        component_id=comp.id,
        contractor_id=user.party_id,
        hoisted_at=body.hoisted_at,
        equipment_no=body.equipment_no,
        signal_worker=body.signal_worker,
        rigger=body.rigger,
        coord_lng=body.coord_lng,
        coord_lat=body.coord_lat,
        result=body.result,
    )
    comp.current_stage = "已吊装"
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return HoistingOut.model_validate(rec)


# ---------- 节点连接 ----------
@router.post("/joint", response_model=JointOut, summary="节点连接登记")
def joint(
    body: JointCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.CONTRACTOR)),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    if not db.query(HoistingRecord).filter(HoistingRecord.component_id == comp.id).first():
        raise HTTPException(status_code=400, detail="构件未吊装，不能登记节点连接")
    rec = JointConnection(
        component_id=comp.id,
        contractor_id=user.party_id,
        grout_at=body.grout_at,
        grout_batch=body.grout_batch,
        bedding_at=body.bedding_at,
        connection_type=body.connection_type,
        operator=body.operator,
        photo_urls=body.photo_urls,
    )
    comp.current_stage = "节点连接"
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return JointOut.model_validate(rec)


# ---------- 隐蔽验收 ----------
@router.post("/concealed", response_model=ConcealedOut, summary="隐蔽工程验收")
def concealed(
    body: ConcealedCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.SUPERVISOR)),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    if not db.query(JointConnection).filter(JointConnection.component_id == comp.id).first():
        raise HTTPException(status_code=400, detail="尚未完成节点连接，不能隐蔽验收")
    rec = ConcealedAcceptance(
        component_id=comp.id,
        supervisor_id=user.party_id,
        accepted_at=body.accepted_at,
        quality_grade=body.quality_grade,
        inspector=body.inspector,
        photo_urls=body.photo_urls,
        video_url=body.video_url,
        conclusion=body.conclusion,
    )
    comp.current_stage = "已隐蔽"
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return ConcealedOut.model_validate(rec)


# ---------- 成品保护 ----------
@router.post("/protection", response_model=ProtectionOut, summary="成品保护登记")
def protection(
    body: ProtectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.CONTRACTOR)),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    if not db.query(ConcealedAcceptance).filter(ConcealedAcceptance.component_id == comp.id).first():
        raise HTTPException(status_code=400, detail="尚未完成隐蔽验收，不能登记成品保护")

    risk_warning = ""
    if any(k in body.mep.lower() for k in ["电", "焊", "切割"]) and "防火" not in body.measures:
        risk_warning = "存在成品破坏隐患：机电动火作业未配套防火保护措施，请及时防护"

    rec = (
        db.query(ProtectionRecord).filter(ProtectionRecord.component_id == comp.id).first()
    )
    if rec:
        rec.decoration = body.decoration
        rec.mep = body.mep
        rec.measures = body.measures
        rec.risk_warning = risk_warning or body.risk_warning
    else:
        rec = ProtectionRecord(
            component_id=comp.id,
            contractor_id=user.party_id,
            decoration=body.decoration,
            mep=body.mep,
            measures=body.measures,
            risk_warning=risk_warning or body.risk_warning,
        )
        db.add(rec)
    comp.current_stage = "成品保护"
    db.commit()
    db.refresh(rec)
    return ProtectionOut.model_validate(rec)
