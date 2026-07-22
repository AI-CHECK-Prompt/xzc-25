"""构件生产、出厂管理。

并发安全说明（多班组平板端抢号场景）：
  原实现 _generate_trace_code 用 count()+1 拼接追溯码，存在 SELECT-then-INSERT
  TOCTOU 竞态：多个班组同时数到 N=5，都生成 PC-...-0006，第二个写入时被唯一
  约束爆掉，整批被拒。

  修复策略：
  1. TraceSequence（工厂 × 当日）行级锁串行化号段分配，杜绝并发改号。
  2. /batch 一次性锁定整段号，整批提交；按 (client_id, batch_id) 幂等回放。
  3. / 单条接口同样走原子分配，保持行为一致。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Sequence

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..db import get_db
from ..models import (
    Component,
    FactoryOutRecord,
    OfflineSyncLog,
    Party,
    PartyRole,
    Project,
    TraceSequence,
    User,
)
from ..schemas import (
    ComponentBatchCreate,
    ComponentBatchItemResult,
    ComponentBatchResult,
    ComponentCreate,
    ComponentOut,
    FactoryOutCreate,
    FactoryOutOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/components", tags=["构件"])


# ---------------------------------------------------------------------------
# 追溯码原子分配
# ---------------------------------------------------------------------------
def _today_midnight() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _allocate_trace_codes(db: Session, factory: Party, count: int) -> List[str]:
    """原子分配 count 个连续追溯码。

    锁粒度 = (factory_id, 当日)：
      - 不同工厂 / 不同日 完全并行。
      - 同工厂同日 串行（单工厂单日通常 < 1000 件，毫秒级开销）。

    重试机制：当日首次插入 TraceSequence 行时可能与并发首插撞车，捕获
    IntegrityError 后重新走 SELECT-FOR-UPDATE 分支，最多 5 次。
    """
    if count <= 0:
        return []
    today = _today_midnight()
    prefix = f"PC-{today.strftime('%Y%m%d')}-{factory.code.upper()}"

    for _ in range(5):
        # 1) 锁住当日序列行
        seq = (
            db.query(TraceSequence)
            .filter(
                TraceSequence.factory_id == factory.id,
                TraceSequence.seq_date == today,
            )
            .with_for_update()
            .first()
        )
        if seq is not None:
            start = seq.next_value
            seq.next_value = start + count
            return [f"{prefix}-{i:04d}" for i in range(start, start + count)]

        # 2) 当日尚未建行：统计已存在追溯码（兼容旧路径已写入的数据）
        existing_count = (
            db.query(func.count(Component.id))
            .filter(Component.trace_code.like(f"{prefix}-%"))
            .scalar()
            or 0
        )
        new_seq = TraceSequence(
            factory_id=factory.id,
            seq_date=today,
            next_value=existing_count + count,
        )
        db.add(new_seq)
        try:
            db.flush()  # 立即触发 INSERT，让唯一约束在此处生效
        except IntegrityError:
            db.rollback()
            continue  # 并发首插撞车，下一轮重试走 SELECT-FOR-UPDATE
        return [f"{prefix}-{i:04d}" for i in range(existing_count + 1, existing_count + 1 + count)]

    log.error("【构件-码段】号段分配重试耗尽 factory=%s count=%d", factory.code, count)
    raise HTTPException(status_code=503, detail="追溯码段分配失败，请重试")


def _build_component(
    *,
    project_id: int,
    factory_id: int,
    body,
    trace_code: str,
) -> Component:
    return Component(
        project_id=project_id,
        factory_id=factory_id,
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
        trace_code=trace_code,
        rfid_tag=f"RFID-{trace_code}",
        qr_payload=f"http://localhost:5173/trace?code={trace_code}",
    )


# ---------------------------------------------------------------------------
# 单条录入
# ---------------------------------------------------------------------------
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

    [code] = _allocate_trace_codes(db, factory, 1)
    comp = _build_component(
        project_id=body.project_id,
        factory_id=factory.id,
        body=body,
        trace_code=code,
    )
    db.add(comp)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        log.error("【构件-创建】追溯码冲突 factory=%s code=%s err=%s", factory.code, code, e)
        raise HTTPException(status_code=409, detail=f"追溯码冲突，请重试：{code}")
    db.refresh(comp)
    log.info("【构件-创建】trace_code=%s factory=%s project=%s", comp.trace_code, factory.code, project.code)
    return ComponentOut.model_validate(comp)


# ---------------------------------------------------------------------------
# 批量录入（高并发安全）
# ---------------------------------------------------------------------------
@router.post(
    "/batch",
    response_model=ComponentBatchResult,
    summary="工厂平板端批量录入（高并发安全 + 幂等）",
)
def create_component_batch(
    body: ComponentBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.FACTORY)),
):
    """并发安全批量录入。

    设计要点：
      - 幂等：client_id + batch_id 命中 OfflineSyncLog 直接返回历史结果，
        弱网/重试不会产生重复数据。
      - 原子号段：整批在同一事务内一次性推进 TraceSequence，组内任意
        两条追溯码都不会与并发批撞车。
      - 整批原子：任一条唯一约束冲突将整体回滚，错误信息返回给前端做
        班组级拆分重试。
    """
    project = db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    factory = db.get(Party, user.party_id)
    if not factory:
        raise HTTPException(status_code=400, detail="用户未关联工厂参与方")

    # ---- 幂等回放 ----
    replay = (
        db.query(OfflineSyncLog)
        .filter(
            OfflineSyncLog.client_id == body.client_id,
            OfflineSyncLog.batch_id == body.batch_id,
        )
        .first()
    )
    if replay and replay.status == "accepted":
        cached = replay.payload or {}
        log.info(
            "【构件-批量-幂等命中】client=%s batch=%s accepted=%d",
            body.client_id, body.batch_id, cached.get("accepted", 0),
        )
        return ComponentBatchResult(
            batch_id=body.batch_id,
            accepted=cached.get("accepted", 0),
            rejected=cached.get("rejected", 0),
            items=[ComponentBatchItemResult(**it) for it in cached.get("items", [])],
            errors=cached.get("errors", []),
            idempotent_replay=True,
        )

    # ---- 一次性号段 ----
    n = len(body.items)
    try:
        codes = _allocate_trace_codes(db, factory, n)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.error("【构件-批量-分配失败】client=%s batch=%s err=%s", body.client_id, body.batch_id, e)
        raise HTTPException(status_code=503, detail="追溯码段分配失败，请重试")

    # ---- 整批构建 + 一次性提交 ----
    items: List[ComponentBatchItemResult] = []
    try:
        for idx, (item, code) in enumerate(zip(body.items, codes)):
            comp = _build_component(
                project_id=body.project_id,
                factory_id=factory.id,
                body=item,
                trace_code=code,
            )
            db.add(comp)
            items.append(
                ComponentBatchItemResult(
                    index=idx,
                    component_id=0,  # flush 后回填
                    trace_code=code,
                    rfid_tag=f"RFID-{code}",
                    qr_payload=f"http://localhost:5173/trace?code={code}",
                )
            )
        db.flush()  # 让唯一约束在此处一次性校验
        db.commit()
    except IntegrityError as e:
        db.rollback()
        log.error(
            "【构件-批量-唯一冲突】client=%s batch=%s factory=%s err=%s",
            body.client_id, body.batch_id, factory.code, e,
        )
        raise HTTPException(
            status_code=409,
            detail="批量提交冲突，请按班组拆分后逐批重试",
        )

    # 回填真实 component_id
    _fill_component_ids(db, items)

    # ---- 写入幂等日志 ----
    payload = {
        "items": [it.model_dump() for it in items],
        "accepted": len(items),
        "rejected": 0,
        "errors": [],
    }
    db.add(
        OfflineSyncLog(
            client_id=body.client_id,
            batch_id=body.batch_id,
            payload=payload,
            status="accepted",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # 并发同 batch 已被另一台平板先写入，吞掉即可
        db.rollback()

    log.info(
        "【构件-批量-完成】client=%s batch=%s factory=%s project=%s accepted=%d range=[%s .. %s]",
        body.client_id, body.batch_id, factory.code, project.code,
        len(items), items[0].trace_code, items[-1].trace_code,
    )
    return ComponentBatchResult(
        batch_id=body.batch_id,
        accepted=len(items),
        rejected=0,
        items=items,
        errors=[],
        idempotent_replay=False,
    )


def _fill_component_ids(db: Session, items: Sequence[ComponentBatchItemResult]) -> None:
    if not items:
        return
    codes = [it.trace_code for it in items]
    rows = (
        db.query(Component.id, Component.trace_code)
        .filter(Component.trace_code.in_(codes))
        .all()
    )
    id_map = {row.trace_code: row.id for row in rows}
    for it in items:
        it.component_id = id_map.get(it.trace_code, 0)


# ---------------------------------------------------------------------------
# 列表 / 详情
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 出厂登记
# ---------------------------------------------------------------------------
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
