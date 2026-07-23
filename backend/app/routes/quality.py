"""质监抽检、整改、构件维护、项目进度可视化。"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..db import get_db
from ..models import (
    Component,
    ComponentLocation,
    MaintenanceCheckRecord,
    Party,
    PartyRole,
    Project,
    ProjectMilestone,
    ProjectNodeStatus,
    QualityInspectionRecord,
    QualityInspectionTask,
    RectificationRecord,
    User,
)
from ..schemas import (
    ComponentLocationOut,
    InspectionRecordCreate,
    InspectionRecordOut,
    InspectionTaskCreate,
    InspectionTaskOut,
    MaintenanceAdvice,
    MaintenanceCheckCreate,
    MaintenanceCheckOut,
    MilestoneCreate,
    MilestoneOut,
    MilestoneProgress,
    ProjectProgressView,
    RectificationCreate,
    RectificationOut,
    RectificationResubmit,
)
from ..services import (
    aggregate_project_progress,
    create_inspection_task,
    resubmit_rectification,
    submit_inspection_record,
    submit_rectification,
    suggest_maintenance_cycle,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["质监 / 维护 / 进度"])


# ---------------------------------------------------------------------------
# 抽检任务（质监机构发起）
# ---------------------------------------------------------------------------
@router.post(
    "/api/quality/inspections/tasks",
    response_model=InspectionTaskOut,
    summary="质监发起抽检任务",
)
def create_task(
    body: InspectionTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.QUALITY)),
):
    comp = db.get(Component, body.component_id)
    task = create_inspection_task(
        db, comp, user, body.stage, body.title, body.requirement,
        body.planned_at, body.inspector_user_id,
    )
    db.commit()
    db.refresh(task)
    log.info(
        "【质监-抽检发起】task_no=%s component=%s stage=%s user=%s",
        task.task_no, comp.trace_code, body.stage, user.username,
    )
    return InspectionTaskOut.model_validate(task)


@router.get(
    "/api/quality/inspections/tasks",
    response_model=List[InspectionTaskOut],
    summary="抽检任务列表（按角色过滤）",
)
def list_tasks(
    project_id: Optional[int] = None,
    only_open: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(QualityInspectionTask)
    if project_id:
        q = q.filter(QualityInspectionTask.project_id == project_id)
    if user.role == PartyRole.QUALITY:
        q = q.filter(QualityInspectionTask.quality_party_id == user.party_id)
    elif user.role == PartyRole.CONTRACTOR:
        # 施工方只看到本工地构件上的任务
        from ..models import Component as C, Project as P
        comp_ids = {
            cid for (cid,) in db.query(C.id).join(P, C.project_id == P.id)
            .filter(P.contractor_party_id == user.party_id).all()
        }
        q = q.filter(QualityInspectionTask.component_id.in_(comp_ids or [0]))
    elif user.role == PartyRole.SUPERVISOR:
        from ..models import Component as C, Project as P
        comp_ids = {
            cid for (cid,) in db.query(C.id).join(P, C.project_id == P.id)
            .filter(P.supervisor_party_id == user.party_id).all()
        }
        q = q.filter(QualityInspectionTask.component_id.in_(comp_ids or [0]))
    if only_open:
        q = q.filter(QualityInspectionTask.is_closed.is_(False))
    return [
        InspectionTaskOut.model_validate(t)
        for t in q.order_by(QualityInspectionTask.id.desc()).all()
    ]


@router.get(
    "/api/quality/inspections/tasks/{task_id}",
    summary="抽检任务详情（含记录与整改）",
)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(QualityInspectionTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    records = (
        db.query(QualityInspectionRecord)
        .filter(QualityInspectionRecord.task_id == task_id)
        .order_by(QualityInspectionRecord.sequence.asc())
        .all()
    )
    rects = (
        db.query(RectificationRecord)
        .filter(RectificationRecord.task_id == task_id)
        .order_by(RectificationRecord.round.asc())
        .all()
    )
    comp = db.get(Component, task.component_id)
    return {
        "task": InspectionTaskOut.model_validate(task).model_dump(mode="json"),
        "component": {"id": comp.id, "trace_code": comp.trace_code} if comp else None,
        "records": [InspectionRecordOut.model_validate(r).model_dump(mode="json") for r in records],
        "rectifications": [RectificationOut.model_validate(r).model_dump(mode="json") for r in rects],
    }


# ---------------------------------------------------------------------------
# 抽检记录（移动端现场录入）
# ---------------------------------------------------------------------------
@router.post(
    "/api/quality/inspections/records",
    response_model=InspectionRecordOut,
    summary="现场录入抽检记录（移动端）",
)
def submit_record(
    body: InspectionRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.QUALITY)),
):
    task = db.get(QualityInspectionTask, body.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="抽检任务不存在")
    rec, _ = submit_inspection_record(
        db, task, user, body.inspected_at, body.location, body.conclusion,
        body.findings, body.measures, body.photo_urls, body.is_reinspection,
    )
    db.commit()
    db.refresh(rec)
    log.info(
        "【质监-抽检录入】task=%s component=%s conclusion=%s reinspection=%s user=%s",
        task.task_no, rec.component_id, body.conclusion.value, body.is_reinspection, user.username,
    )
    return InspectionRecordOut.model_validate(rec)


@router.get(
    "/api/quality/inspections/records",
    response_model=List[InspectionRecordOut],
    summary="抽检记录列表",
)
def list_records(
    task_id: Optional[int] = None,
    component_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(QualityInspectionRecord)
    if task_id:
        q = q.filter(QualityInspectionRecord.task_id == task_id)
    if component_id:
        q = q.filter(QualityInspectionRecord.component_id == component_id)
    return [
        InspectionRecordOut.model_validate(r)
        for r in q.order_by(QualityInspectionRecord.id.desc()).all()
    ]


# ---------------------------------------------------------------------------
# 整改（施工方处理 / 质监复核）
# ---------------------------------------------------------------------------
@router.post(
    "/api/quality/rectifications",
    response_model=RectificationOut,
    summary="施工方提交整改方案 / 过程",
)
def create_rectification(
    body: RectificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.CONTRACTOR)),
):
    task = db.get(QualityInspectionTask, body.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="抽检任务不存在")
    rect = (
        db.query(RectificationRecord)
        .filter(RectificationRecord.task_id == task.id)
        .order_by(RectificationRecord.round.desc(), RectificationRecord.id.desc())
        .first()
    )
    if not rect:
        raise HTTPException(status_code=404, detail="该任务无对应整改单")
    submit_rectification(
        db, rect, user, body.plan, body.progress_note, body.photo_urls, body.deadline,
    )
    db.commit()
    db.refresh(rect)
    return RectificationOut.model_validate(rect)


@router.post(
    "/api/quality/rectifications/{rect_id}/resubmit",
    response_model=RectificationOut,
    summary="施工方申请复核",
)
def resubmit(rect_id: int, body: RectificationResubmit, db: Session = Depends(get_db),
             user: User = Depends(require_roles(PartyRole.CONTRACTOR))):
    rect = db.get(RectificationRecord, rect_id)
    if not rect:
        raise HTTPException(status_code=404, detail="整改单不存在")
    resubmit_rectification(db, rect, user, body.result_note)
    db.commit()
    db.refresh(rect)
    return RectificationOut.model_validate(rect)


@router.get(
    "/api/quality/rectifications",
    response_model=List[RectificationOut],
    summary="整改单列表",
)
def list_rectifications(
    only_open: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(RectificationRecord)
    if user.role == PartyRole.CONTRACTOR:
        q = q.filter(RectificationRecord.contractor_party_id == user.party_id)
    elif user.role == PartyRole.QUALITY:
        from ..models import QualityInspectionTask as T
        q = q.join(T, RectificationRecord.task_id == T.id).filter(
            T.quality_party_id == user.party_id,
        )
    if only_open:
        from ..models import RectificationStatus as RS
        q = q.filter(RectificationRecord.status != RS.CLOSED)
    return [
        RectificationOut.model_validate(r)
        for r in q.order_by(RectificationRecord.id.desc()).all()
    ]


# ---------------------------------------------------------------------------
# 维护检查（运营方）
# ---------------------------------------------------------------------------
@router.post(
    "/api/maintenance/checks",
    response_model=MaintenanceCheckOut,
    summary="登记维护检查记录",
)
def create_check(
    body: MaintenanceCheckCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = db.get(Component, body.component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    if comp.current_stage != "已归档":
        raise HTTPException(
            status_code=409,
            detail="仅已完成档案归档的构件支持运营期维护登记",
        )
    rec = MaintenanceCheckRecord(
        component_id=comp.id,
        project_id=comp.project_id,
        operator_party_id=user.party_id,
        operator_user_id=user.id,
        checked_at=body.checked_at,
        finding=body.finding,
        description=body.description,
        action_taken=body.action_taken,
        next_check_in_days=body.next_check_in_days,
        photo_urls=body.photo_urls,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return MaintenanceCheckOut.model_validate(rec)


@router.get(
    "/api/maintenance/checks",
    response_model=List[MaintenanceCheckOut],
    summary="维护检查记录列表",
)
def list_checks(
    component_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(MaintenanceCheckRecord)
    if component_id:
        q = q.filter(MaintenanceCheckRecord.component_id == component_id)
    if user.role == PartyRole.OWNER:
        # 建设单位：仅看本项目的构件
        from ..models import Project as P
        proj_ids = {p.id for p in db.query(P.id).filter(P.owner_party_id == user.party_id).all()}
        q = q.filter(MaintenanceCheckRecord.project_id.in_(proj_ids or [0]))
    return [
        MaintenanceCheckOut.model_validate(r)
        for r in q.order_by(MaintenanceCheckRecord.checked_at.desc()).all()
    ]


@router.get(
    "/api/maintenance/advice/{component_id}",
    response_model=MaintenanceAdvice,
    summary="构件维护周期建议",
)
def get_advice(
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    comp = db.get(Component, component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="构件不存在")
    return suggest_maintenance_cycle(db, comp)


# ---------------------------------------------------------------------------
# 项目进度可视化（甘特 / 看板 / 地图）
# ---------------------------------------------------------------------------
@router.post(
    "/api/projects/milestones",
    response_model=MilestoneOut,
    summary="定义项目关键节点",
)
def create_milestone(
    body: MilestoneCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(PartyRole.OWNER)),
):
    p = db.get(Project, body.project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    if p.owner_party_id != user.party_id:
        raise HTTPException(status_code=403, detail="仅本项目业主可定义节点")
    m = ProjectMilestone(
        project_id=body.project_id,
        code=body.code,
        name=body.name,
        stage=body.stage,
        planned_at=body.planned_at,
        baseline_at=body.baseline_at,
        weight=body.weight,
        sort_no=body.sort_no,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return MilestoneOut.model_validate(m)


@router.get(
    "/api/projects/{project_id}/milestones",
    response_model=List[MilestoneOut],
    summary="项目节点列表",
)
def list_milestones(project_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    rows = (
        db.query(ProjectMilestone)
        .filter(ProjectMilestone.project_id == project_id)
        .order_by(ProjectMilestone.sort_no.asc(), ProjectMilestone.id.asc())
        .all()
    )
    return [MilestoneOut.model_validate(r) for r in rows]


@router.get(
    "/api/projects/{project_id}/progress",
    response_model=ProjectProgressView,
    summary="项目进度（三视图共享数据源）",
)
def get_progress(project_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = aggregate_project_progress(db, p)

    return ProjectProgressView(
        project_id=p.id,
        project_name=p.name,
        overall_pct=data["overall_pct"],
        stage_buckets=data["stage_buckets"],
        blocked_components=data["blocked_components"],
        rect_open=data["rect_open"],
        inspection_open=data["inspection_open"],
        milestones=[
            MilestoneProgress(
                milestone=MilestoneOut.model_validate(mp["milestone"]),
                status=mp["status"],
                actual_at=mp["actual_at"],
                progress_pct=mp["progress_pct"],
                blocked_components=mp["blocked_components"],
            )
            for mp in data["milestones"]
        ],
        locations=[
            ComponentLocationOut.model_validate(loc) for loc in data["locations"]
        ],
    )


@router.post(
    "/api/projects/{project_id}/components/{component_id}/location",
    response_model=ComponentLocationOut,
    summary="登记 / 更新构件工地坐标",
)
def upsert_location(
    project_id: int, component_id: int,
    longitude: float, latitude: float,
    building: str = "", floor: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in (PartyRole.CONTRACTOR, PartyRole.OWNER, PartyRole.QUALITY):
        raise HTTPException(status_code=403, detail="仅施工方 / 建设方 / 质监可登记坐标")
    comp = db.get(Component, component_id)
    if not comp or comp.project_id != project_id:
        raise HTTPException(status_code=404, detail="构件不存在或不属于该项目")
    loc = (
        db.query(ComponentLocation)
        .filter(ComponentLocation.component_id == component_id)
        .first()
    )
    if loc:
        loc.longitude = longitude
        loc.latitude = latitude
        loc.building = building
        loc.floor = floor
    else:
        loc = ComponentLocation(
            component_id=component_id,
            project_id=project_id,
            longitude=longitude,
            latitude=latitude,
            building=building,
            floor=floor,
        )
        db.add(loc)
    db.commit()
    db.refresh(loc)
    return ComponentLocationOut.model_validate(loc)
