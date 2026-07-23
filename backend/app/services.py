"""服务层：业务聚合。"""
from __future__ import annotations

import io
import json
import math
import os
import zipfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    AcceptanceResult,
    ArchivePackage,
    ArchiveStatus,
    Component,
    ComponentLocation,
    ConcealedAcceptance,
    FactoryOutRecord,
    HoistingRecord,
    InspectionConclusion,
    JointConnection,
    MaintenanceCheckRecord,
    MaintenanceFinding,
    Party,
    PartyRole,
    Project,
    ProjectMilestone,
    ProjectNodeStatus,
    ProtectionRecord,
    QualityInspectionRecord,
    QualityInspectionTask,
    RectificationRecord,
    RectificationStatus,
    SiteEntryRecord,
    TransportAlert,
    TransportTelemetry,
    User,
)
from .schemas import TraceResponse, TraceTimelineItem

settings = get_settings()


# ---------------------------------------------------------------------------
# 追溯聚合
# ---------------------------------------------------------------------------
def build_trace(db: Session, trace_code: str, requester: User) -> TraceResponse:
    """根据唯一追溯码聚合全链路记录。

    权责隔离：返回的数据按请求方角色裁剪，跨方数据只显示必要元信息。
    """
    comp: Optional[Component] = db.query(Component).filter(Component.trace_code == trace_code).first()
    if not comp:
        raise HTTPException(status_code=404, detail=f"未找到追溯码 {trace_code} 对应的构件")

    # 跨方访问时仅展示元信息
    can_view_full = requester.role in (
        PartyRole.OWNER,
        PartyRole.QUALITY,
        PartyRole.FACTORY,
    ) or (
        requester.role == PartyRole.CONTRACTOR and comp.current_stage
        in ("已吊装", "节点连接", "已隐蔽", "成品保护", "已归档")
    ) or (
        requester.role == PartyRole.SUPERVISOR and comp.current_stage
        in ("节点连接", "已隐蔽", "成品保护", "已归档")
    ) or (
        requester.role == PartyRole.TRANSPORT and comp.current_stage
        in ("运输中", "已到达", "已卸货", "已进场", "已吊装", "节点连接", "已隐蔽", "成品保护", "已归档")
    )

    timeline: List[TraceTimelineItem] = []

    factory: Optional[Party] = db.get(Party, comp.factory_id)
    project: Optional[Project] = db.get(Project, comp.project_id)

    timeline.append(
        TraceTimelineItem(
            stage="构件生产",
            occurred_at=comp.pour_at,
            actor=factory.name if factory else "—",
            party_role=PartyRole.FACTORY,
            summary=(
                f"模具 {comp.mould_no}，钢筋批号 {comp.rebar_batch}，"
                f"配合比 {comp.concrete_ratio}，强度报告 {comp.strength_report}，"
                f"出厂自检 {comp.factory_inspection.value}"
            ),
            extras={
                "trace_code": comp.trace_code,
                "rfid": comp.rfid_tag,
                "spec": comp.spec,
                "embedded_parts": comp.embedded_parts,
            },
        )
    )

    out_rec: Optional[FactoryOutRecord] = (
        db.query(FactoryOutRecord).filter(FactoryOutRecord.component_id == comp.id).first()
    )
    if out_rec:
        transport_party: Optional[Party] = db.get(Party, out_rec.transport_party_id)
        timeline.append(
            TraceTimelineItem(
                stage="构件出厂",
                occurred_at=out_rec.out_at,
                actor=transport_party.name if transport_party else "—",
                party_role=PartyRole.FACTORY,
                summary=(
                    f"车辆 {out_rec.vehicle_no}，司机 {out_rec.driver}，"
                    f"出厂检验 {out_rec.inspection_conclusion.value}"
                ),
                extras={"route_plan": out_rec.route_plan},
            )
        )

        if can_view_full:
            tels = (
                db.query(TransportTelemetry)
                .filter(TransportTelemetry.component_id == comp.id)
                .order_by(TransportTelemetry.reported_at.asc())
                .all()
            )
            alerts = (
                db.query(TransportAlert)
                .filter(TransportAlert.component_id == comp.id)
                .order_by(TransportAlert.created_at.asc())
                .all()
            )
            # 按 telemetry_id 聚合：同一时刻可能同时存在多条不同类型的告警
            # （例如温度越界 + 偏离路线），需全部独立展示，不能只取第一条
            alerts_by_tel: Dict[int, List[TransportAlert]] = {}
            for a in alerts:
                alerts_by_tel.setdefault(a.telemetry_id, []).append(a)
            for idx, t in enumerate(tels):
                alerts_for_this = alerts_by_tel.get(t.id, [])
                # 告警信息单独放到 extras，避免与轨迹 summary 同行拼接；
                # 不同类型告警在追溯详情页以独立标签展示，运营人员可一眼区分
                # 构件当前究竟是温度越界还是位置偏离状态
                timeline.append(
                    TraceTimelineItem(
                        stage="运输轨迹" if idx == 0 else f"运输轨迹-{idx + 1}",
                        occurred_at=t.reported_at,
                        actor=transport_party.name if transport_party else "—",
                        party_role=PartyRole.TRANSPORT,
                        summary=(
                            f"位置 ({t.latitude:.4f}, {t.longitude:.4f})，"
                            f"温度 {t.temperature:.1f}℃ / 湿度 {t.humidity:.1f}%RH，"
                            f"状态 {t.status.value}"
                        ),
                        extras={
                            "telemetry_id": t.id,
                            "alerts": [
                                {
                                    "id": a.id,
                                    "alert_type": a.alert_type,
                                    "detail": a.detail,
                                    "resolved": a.resolved,
                                    "created_at": a.created_at.isoformat() if a.created_at else None,
                                }
                                for a in alerts_for_this
                            ],
                        },
                    )
                )

    site: Optional[SiteEntryRecord] = (
        db.query(SiteEntryRecord).filter(SiteEntryRecord.component_id == comp.id).first()
    )
    if site:
        contractor: Optional[Party] = db.get(Party, site.contractor_id)
        timeline.append(
            TraceTimelineItem(
                stage="构件进场",
                occurred_at=site.entered_at,
                actor=contractor.name if contractor else "—",
                party_role=PartyRole.CONTRACTOR,
                summary=(
                    f"堆放位置 {site.stack_location}，验收人 {site.inspector}，"
                    f"结论 {site.acceptance.value}，备注 {site.remark or '—'}"
                ),
            )
        )

    hoist: Optional[HoistingRecord] = (
        db.query(HoistingRecord).filter(HoistingRecord.component_id == comp.id).first()
    )
    if hoist:
        contractor = db.get(Party, hoist.contractor_id)
        timeline.append(
            TraceTimelineItem(
                stage="构件吊装",
                occurred_at=hoist.hoisted_at,
                actor=contractor.name if contractor else "—",
                party_role=PartyRole.CONTRACTOR,
                summary=(
                    f"设备 {hoist.equipment_no}，信号工 {hoist.signal_worker}，"
                    f"司索工 {hoist.rigger}，结果 {hoist.result.value}"
                ),
                extras={"coord": [hoist.coord_lng, hoist.coord_lat]},
            )
        )

    joint: Optional[JointConnection] = (
        db.query(JointConnection).filter(JointConnection.component_id == comp.id).first()
    )
    if joint:
        contractor = db.get(Party, joint.contractor_id)
        timeline.append(
            TraceTimelineItem(
                stage="节点连接",
                occurred_at=joint.grout_at,
                actor=contractor.name if contractor else "—",
                party_role=PartyRole.CONTRACTOR,
                summary=(
                    f"灌浆料批号 {joint.grout_batch}，连接方式 {joint.connection_type.value}，"
                    f"作业员 {joint.operator}"
                ),
            )
        )

    concealed: Optional[ConcealedAcceptance] = (
        db.query(ConcealedAcceptance).filter(ConcealedAcceptance.component_id == comp.id).first()
    )
    if concealed:
        supervisor: Optional[Party] = db.get(Party, concealed.supervisor_id)
        timeline.append(
            TraceTimelineItem(
                stage="隐蔽验收",
                occurred_at=concealed.accepted_at,
                actor=supervisor.name if supervisor else "—",
                party_role=PartyRole.SUPERVISOR,
                summary=(
                    f"质量等级 {concealed.quality_grade}，监理员 {concealed.inspector}，"
                    f"结论 {concealed.conclusion or '合格'}"
                ),
            )
        )

    protect: Optional[ProtectionRecord] = (
        db.query(ProtectionRecord).filter(ProtectionRecord.component_id == comp.id).first()
    )
    if protect:
        contractor = db.get(Party, protect.contractor_id)
        timeline.append(
            TraceTimelineItem(
                stage="成品保护",
                occurred_at=protect.updated_at,
                actor=contractor.name if contractor else "—",
                party_role=PartyRole.CONTRACTOR,
                summary=(
                    f"装饰 {protect.decoration or '—'}，机电 {protect.mep or '—'}，"
                    f"措施 {protect.measures or '—'}"
                    + (f"｜风险提示 {protect.risk_warning}" if protect.risk_warning else "")
                ),
            )
        )

    archives = (
        db.query(ArchivePackage)
        .filter(ArchivePackage.component_id == comp.id)
        .order_by(ArchivePackage.created_at.asc())
        .all()
    )
    if archives:
        archive = archives[-1]
        owner: Optional[Party] = db.get(Party, archive.owner_id)
        timeline.append(
            TraceTimelineItem(
                stage="档案归档",
                occurred_at=archive.created_at,
                actor=owner.name if owner else "—",
                party_role=PartyRole.OWNER,
                summary=(
                    f"档案号 {archive.archive_no}，状态 {archive.status.value}，"
                    f"项目 {project.name if project else '—'}"
                ),
            )
        )

    # 质监抽检 / 整改（建设方 / 质监可见全量；其他方只看到与自己相关的）
    can_see_quality = requester.role in (
        PartyRole.OWNER, PartyRole.QUALITY, PartyRole.CONTRACTOR, PartyRole.SUPERVISOR,
    )
    if can_see_quality:
        tasks = (
            db.query(QualityInspectionTask)
            .filter(QualityInspectionTask.component_id == comp.id)
            .order_by(QualityInspectionTask.created_at.asc())
            .all()
        )
        for t in tasks:
            inspector: Optional[User] = db.get(User, t.initiated_by)
            quality_party: Optional[Party] = db.get(Party, t.quality_party_id)
            timeline.append(
                TraceTimelineItem(
                    stage=f"质监抽检·{t.stage}",
                    occurred_at=t.created_at,
                    actor=inspector.full_name if inspector else "—",
                    party_role=PartyRole.QUALITY,
                    summary=(
                        f"任务号 {t.task_no}，工序 {t.stage}，"
                        f"状态 {('已闭环' if t.is_closed else '进行中')}，"
                        f"质监方 {quality_party.name if quality_party else '—'}"
                    ),
                    extras={
                        "task_id": t.id,
                        "title": t.title,
                        "requirement": t.requirement,
                    },
                )
            )
            records = (
                db.query(QualityInspectionRecord)
                .filter(QualityInspectionRecord.task_id == t.id)
                .order_by(QualityInspectionRecord.sequence.asc())
                .all()
            )
            for r in records:
                r_user: Optional[User] = db.get(User, r.inspector_user_id)
                timeline.append(
                    TraceTimelineItem(
                        stage=("复核记录" if r.is_reinspection else "抽检记录"),
                        occurred_at=r.inspected_at,
                        actor=r_user.full_name if r_user else "—",
                        party_role=PartyRole.QUALITY,
                        summary=(
                            f"第 {r.sequence} 次抽检，结论 {r.conclusion.value}，"
                            f"地点 {r.location or '—'}，"
                            f"发现 {r.findings or '—'}"
                        ),
                        extras={"task_id": t.id, "measures": r.measures},
                    )
                )
            rects = (
                db.query(RectificationRecord)
                .filter(RectificationRecord.task_id == t.id)
                .order_by(RectificationRecord.round.asc())
                .all()
            )
            for r in rects:
                rect_party: Optional[Party] = db.get(Party, r.contractor_party_id)
                timeline.append(
                    TraceTimelineItem(
                        stage=f"整改·第{r.round}轮",
                        occurred_at=r.created_at,
                        actor=rect_party.name if rect_party else "—",
                        party_role=PartyRole.CONTRACTOR,
                        summary=(
                            f"状态 {r.status.value}，方案 {r.plan or '—'}"
                        ),
                        extras={
                            "rectification_id": r.id,
                            "progress": r.progress_note,
                            "result": r.result_note,
                        },
                    )
                )

    # 维护检查（运营期）
    if requester.role in (PartyRole.OWNER, PartyRole.QUALITY, PartyRole.SUPERVISOR):
        checks = (
            db.query(MaintenanceCheckRecord)
            .filter(MaintenanceCheckRecord.component_id == comp.id)
            .order_by(MaintenanceCheckRecord.checked_at.asc())
            .all()
        )
        for m in checks:
            op_party: Optional[Party] = db.get(Party, m.operator_party_id)
            timeline.append(
                TraceTimelineItem(
                    stage="维护检查",
                    occurred_at=m.checked_at,
                    actor=op_party.name if op_party else "—",
                    party_role=PartyRole.OWNER,
                    summary=(
                        f"发现 {m.finding.value}，描述 {m.description or '—'}，"
                        f"处理 {m.action_taken or '—'}，"
                        f"下次检查 {m.next_check_in_days or '平台建议'} 天后"
                    ),
                )
            )

    from .schemas import ComponentOut, ArchiveOut

    return TraceResponse(
        component=ComponentOut.model_validate(comp),
        timeline=timeline,
        archives=[ArchiveOut.model_validate(a) for a in archives],
    )


# ---------------------------------------------------------------------------
# 运输告警
# ---------------------------------------------------------------------------
TEMP_HIGH = 60.0
TEMP_LOW = -10.0
HUMIDITY_HIGH = 95.0
OVERSTAY_MINUTES = 30
ROUTE_DEVIATION_KM = 2.0  # 简化判定：相邻点距 > 2km 视为偏离


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """使用 haversine 计算两点距离（km）。"""
    R = 6371.0
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def detect_alerts(db: Session, telemetry: TransportTelemetry) -> List[TransportAlert]:
    """根据单条 telemetry 检测告警。"""
    alerts: List[TransportAlert] = []
    if telemetry.temperature > TEMP_HIGH or telemetry.temperature < TEMP_LOW or telemetry.humidity > HUMIDITY_HIGH:
        a = TransportAlert(
            component_id=telemetry.component_id,
            telemetry_id=telemetry.id,
            alert_type="TEMP_OUT",
            detail=(
                f"温湿度越界：温度 {telemetry.temperature:.1f}℃、"
                f"湿度 {telemetry.humidity:.1f}%RH"
            ),
        )
        db.add(a)
        alerts.append(a)

    prev = (
        db.query(TransportTelemetry)
        .filter(
            TransportTelemetry.component_id == telemetry.component_id,
            TransportTelemetry.id != telemetry.id,
        )
        .order_by(TransportTelemetry.reported_at.desc())
        .first()
    )
    if prev:
        dist = _distance_km(prev.latitude, prev.longitude, telemetry.latitude, telemetry.longitude)
        gap_min = (telemetry.reported_at - prev.reported_at).total_seconds() / 60.0
        if dist > ROUTE_DEVIATION_KM and gap_min > 0 and dist / max(gap_min, 1e-3) > 1.5:
            a = TransportAlert(
                component_id=telemetry.component_id,
                telemetry_id=telemetry.id,
                alert_type="OFF_ROUTE",
                detail=f"相邻两点距离 {dist:.1f}km，疑似偏离路线",
            )
            db.add(a)
            alerts.append(a)
        if gap_min > OVERSTAY_MINUTES and dist < 0.1:
            a = TransportAlert(
                component_id=telemetry.component_id,
                telemetry_id=telemetry.id,
                alert_type="OVERSTAY",
                detail=f"停留 {gap_min:.0f} 分钟且位移极小",
            )
            db.add(a)
            alerts.append(a)
    return alerts


# ---------------------------------------------------------------------------
# 档案归档
# ---------------------------------------------------------------------------
def _cleanup_obsolete_archive_file(old_path: str, new_path: str) -> None:
    """清理同一构件再次归档时遗留的旧 ZIP 文件。

    - 旧路径为空 / 与新路径相同 → 跳过；
    - 旧文件不在存储目录下 → 不动，避免误删（防御性检查）；
    - 文件不存在 → 静默跳过（可能运维已手工清理）；
    - 真正删除失败（权限、被占用等）→ 仅打印告警，不阻断新档案生成。
    """
    if not old_path or old_path == new_path:
        return
    try:
        storage_dir = os.path.realpath(settings.storage_dir)
        real_old = os.path.realpath(old_path)
    except Exception:  # noqa: BLE001
        return
    # 必须位于 storage_dir 之下，避免误删配置 / 业务关键文件
    if not (real_old == storage_dir or real_old.startswith(storage_dir + os.sep)):
        return
    try:
        if os.path.isfile(real_old):
            os.remove(real_old)
    except FileNotFoundError:
        # 已被其他流程清理，不算错误
        return
    except OSError as exc:  # noqa: BLE001
        # 权限不足 / 文件被占用：不阻断新档案归档，但要让运维看到
        print(f"[archives] 清理旧档案文件失败（不影响新档案生成）：{real_old} -> {exc}")


def generate_archive(db: Session, component: Component, owner: User) -> ArchivePackage:
    """根据全链路数据生成电子档案包 ZIP，并落库。"""
    os.makedirs(settings.storage_dir, exist_ok=True)

    payload = build_trace(db, component.trace_code, owner).model_dump(mode="json")
    archive_no = (
        f"ARCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-{component.trace_code[-6:]}"
    )
    file_path = os.path.join(settings.storage_dir, f"{archive_no}.zip")

    manifest = {
        "档案号": archive_no,
        "规范版本": "城建档案管理规范 2024 版",
        "生成时间": datetime.now().isoformat(timespec="seconds"),
        "构件追溯码": component.trace_code,
        "项目": db.get(Project, component.project_id).name if db.get(Project, component.project_id) else "",
        "工厂": db.get(Party, component.factory_id).name if db.get(Party, component.factory_id) else "",
        "权责矩阵": {
            "factory": "生产质量与出厂检验",
            "transport": "运输过程完好与路线合规",
            "contractor": "进场、吊装、节点、成品保护",
            "supervisor": "隐蔽验收与质量评定",
            "owner": "多方协调与档案归档",
            "quality": "监督抽检与行政处罚",
        },
        "全链路": payload,
    }

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        zf.writestr("trace_timeline.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        zf.writestr(
            "cover.txt",
            (
                "装配式建筑构件全过程质量追溯电子档案\n"
                f"档案号：{archive_no}\n"
                f"构件追溯码：{component.trace_code}\n"
                f"生成时间：{manifest['生成时间']}\n"
                f"建设单位：{owner.full_name}\n"
            ),
        )

    existing = (
        db.query(ArchivePackage).filter(ArchivePackage.component_id == component.id).first()
    )
    if existing:
        # 同一构件再次归档时，档案号（带时间戳）会重新生成，磁盘上会
        # 多出一份新的 ZIP。DB 记录通过唯一约束只能保留一条，因此需要
        # 在切换 file_path 之前先清理旧文件，否则存储目录会不断堆积
        # 与档案号仅差时间戳后缀的「历史档案包」，长期运行后占用大量
        # 磁盘空间且无法识别为可清理数据。
        _cleanup_obsolete_archive_file(existing.file_path, file_path)
        existing.archive_no = archive_no
        existing.file_path = file_path
        existing.payload = manifest
        existing.status = ArchiveStatus.GENERATED
        existing.created_at = datetime.now()
        db.flush()
        return existing

    archive = ArchivePackage(
        component_id=component.id,
        project_id=component.project_id,
        owner_id=owner.party_id,
        archive_no=archive_no,
        file_path=file_path,
        payload=manifest,
        status=ArchiveStatus.GENERATED,
    )
    db.add(archive)
    db.flush()
    return archive


# ---------------------------------------------------------------------------
# 离线同步
# ---------------------------------------------------------------------------
EVENT_TO_MODEL = {
    "site_entry": SiteEntryRecord,
    "hoisting": HoistingRecord,
    "joint": JointConnection,
    "concealed": ConcealedAcceptance,
    "protection": ProtectionRecord,
}


def apply_offline_event(db: Session, event_type: str, payload: dict, occurred_at: datetime, requester: User) -> str:
    """将离线事件落到对应主表，必要时做权责校验。"""
    if event_type not in EVENT_TO_MODEL:
        return f"unsupported event_type: {event_type}"

    model = EVENT_TO_MODEL[event_type]
    component: Optional[Component] = db.get(Component, payload.get("component_id"))
    if not component:
        return f"component {payload.get('component_id')} not found"

    # 权责校验
    role_to_owner_field = {
        "site_entry": ("contractor", PartyRole.CONTRACTOR, "contractor_id"),
        "hoisting": ("contractor", PartyRole.CONTRACTOR, "contractor_id"),
        "joint": ("contractor", PartyRole.CONTRACTOR, "contractor_id"),
        "concealed": ("supervisor", PartyRole.SUPERVISOR, "supervisor_id"),
        "protection": ("contractor", PartyRole.CONTRACTOR, "contractor_id"),
    }
    role, expected, field = role_to_owner_field[event_type]
    if requester.role != expected:
        return f"role {requester.role.value} cannot submit {event_type}"

    payload = {**payload, field: requester.party_id}
    if "component_id" not in payload:
        return "missing component_id"

    obj = model(**payload)
    db.add(obj)
    return "ok"


# ---------------------------------------------------------------------------
# 质监抽检：任务 / 记录 / 整改 / 阻断
# ---------------------------------------------------------------------------
# 工序顺序：抽检只允许在构件已抵达对应阶段时才能开展
STAGE_ORDER = [
    "已生产", "运输中", "已到场", "已进场", "进场不合格",
    "已吊装", "节点连接", "已隐蔽", "成品保护", "已归档",
]


def _stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def has_blocking_inspection(db: Session, component_id: int, target_stage: str) -> bool:
    """判定某构件在向 target_stage 推进前，是否存在尚未闭环的不合格抽检。

    抽检不合格的构件进入「待整改 / 整改中 / 已申请复核」时，平台禁止
    其进入该抽检对应的下游工序；整改完成（结论=整改后合格）后，阻断解除。
    """
    target_rank = _stage_rank(target_stage)
    if target_rank < 0:
        return False
    open_tasks = (
        db.query(QualityInspectionTask)
        .filter(
            QualityInspectionTask.component_id == component_id,
            QualityInspectionTask.is_closed.is_(False),
        )
        .all()
    )
    for t in open_tasks:
        stage_rank = _stage_rank(t.stage)
        if stage_rank < 0 or stage_rank >= target_rank:
            continue
        latest = (
            db.query(QualityInspectionRecord)
            .filter(QualityInspectionRecord.task_id == t.id)
            .order_by(QualityInspectionRecord.sequence.desc(), QualityInspectionRecord.id.desc())
            .first()
        )
        if not latest or latest.conclusion != InspectionConclusion.UNPASSED:
            continue
        rect = (
            db.query(RectificationRecord)
            .filter(RectificationRecord.task_id == t.id)
            .order_by(RectificationRecord.round.desc(), RectificationRecord.id.desc())
            .first()
        )
        if rect and rect.status == RectificationStatus.CLOSED:
            continue
        return True
    return False


def create_inspection_task(
    db: Session,
    component: Component,
    requester: User,
    stage: str,
    title: str,
    requirement: str,
    planned_at: Optional[datetime],
    inspector_user_id: Optional[int],
) -> QualityInspectionTask:
    if requester.role != PartyRole.QUALITY:
        raise HTTPException(status_code=403, detail="仅质量监督机构可发起抽检任务")
    if not component:
        raise HTTPException(status_code=404, detail="构件不存在")

    # 一个构件同一工序上只能存在一个未闭环的抽检任务
    open_token = "open"
    exists = (
        db.query(QualityInspectionTask)
        .filter(
            QualityInspectionTask.component_id == component.id,
            QualityInspectionTask.stage == stage,
            QualityInspectionTask.open_token == open_token,
        )
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=409,
            detail=f"该构件在工序「{stage}」已有未闭环抽检任务（{exists.task_no}）",
        )

    task_no = (
        f"INS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{component.trace_code[-6:]}"
    )
    task = QualityInspectionTask(
        task_no=task_no,
        component_id=component.id,
        project_id=component.project_id,
        quality_party_id=requester.party_id,
        initiated_by=requester.id,
        inspector_user_id=inspector_user_id,
        stage=stage,
        title=title,
        requirement=requirement,
        planned_at=planned_at,
        open_token=open_token,
        is_closed=False,
    )
    db.add(task)
    db.flush()
    return task


def submit_inspection_record(
    db: Session,
    task: QualityInspectionTask,
    requester: User,
    inspected_at: datetime,
    location: str,
    conclusion: InspectionConclusion,
    findings: str,
    measures: str,
    photo_urls: List[str],
    is_reinspection: bool,
) -> tuple[QualityInspectionRecord, Optional[RectificationRecord]]:
    if requester.role != PartyRole.QUALITY:
        raise HTTPException(status_code=403, detail="仅质量监督机构可录入抽检记录")
    if task.is_closed:
        raise HTTPException(status_code=409, detail="任务已闭环，不能继续录入")

    if is_reinspection and task.inspector_user_id and requester.id != task.inspector_user_id:
        raise HTTPException(
            status_code=403,
            detail="复核必须由原抽检人完成，请切换为指定复核人账号",
        )

    # sequence 递增
    last_seq = (
        db.query(QualityInspectionRecord.sequence)
        .filter(QualityInspectionRecord.task_id == task.id)
        .order_by(QualityInspectionRecord.sequence.desc(), QualityInspectionRecord.id.desc())
        .first()
    )
    seq = (last_seq[0] if last_seq else 0) + 1

    rec = QualityInspectionRecord(
        task_id=task.id,
        component_id=task.component_id,
        inspector_user_id=requester.id,
        sequence=seq,
        inspected_at=inspected_at,
        location=location,
        conclusion=conclusion,
        findings=findings,
        measures=measures,
        photo_urls=photo_urls,
        is_reinspection=is_reinspection,
    )
    db.add(rec)
    db.flush()

    rect: Optional[RectificationRecord] = None
    if conclusion == InspectionConclusion.UNPASSED:
        # 抽检不合格 → 自动开整改（首轮）
        contractor_id = _lookup_component_contractor(db, task.component_id)
        rect = RectificationRecord(
            task_id=task.id,
            component_id=task.component_id,
            contractor_party_id=contractor_id or 0,
            round=1,
            status=RectificationStatus.PENDING,
        )
        db.add(rect)
        db.flush()  # 让 rect.id 在调用方立即可用
    elif conclusion == InspectionConclusion.RECTIFIED and is_reinspection:
        # 复核合格 → 关闭对应整改单，关闭任务
        rect = (
            db.query(RectificationRecord)
            .filter(RectificationRecord.task_id == task.id)
            .order_by(RectificationRecord.round.desc(), RectificationRecord.id.desc())
            .first()
        )
        if rect:
            rect.status = RectificationStatus.CLOSED
            rect.closed_at = datetime.now()
        task.is_closed = True
        task.closed_at = datetime.now()
        # 清理 open_token（确保后续同工序抽检可以重新开）
        task.open_token = f"closed-{task.id}"
    return rec, rect


def _lookup_component_contractor(db: Session, component_id: int) -> Optional[int]:
    """从历史施工记录中反查构件所属施工方，用于自动开整改。"""
    for model, field in (
        (SiteEntryRecord, "contractor_id"),
        (HoistingRecord, "contractor_id"),
        (JointConnection, "contractor_id"),
        (ProtectionRecord, "contractor_id"),
    ):
        row = db.query(getattr(model, field)).filter(model.component_id == component_id).first()
        if row and row[0]:
            return int(row[0])
    return None


def submit_rectification(
    db: Session, rect: RectificationRecord, requester: User,
    plan: str, progress_note: str, photo_urls: List[str], deadline: Optional[datetime],
) -> RectificationRecord:
    if requester.role != PartyRole.CONTRACTOR:
        raise HTTPException(status_code=403, detail="仅施工总承包可提交整改")
    if requester.party_id != rect.contractor_party_id:
        raise HTTPException(status_code=403, detail="仅本工地施工方能处理本构件的整改")
    if rect.status == RectificationStatus.CLOSED:
        raise HTTPException(status_code=409, detail="整改单已闭环")
    if rect.status == RectificationStatus.PENDING:
        rect.status = RectificationStatus.IN_PROGRESS
    rect.plan = plan or rect.plan
    rect.progress_note = progress_note or rect.progress_note
    if photo_urls:
        rect.photo_urls = photo_urls
    if deadline:
        rect.deadline = deadline
    return rect


def resubmit_rectification(
    db: Session, rect: RectificationRecord, requester: User, result_note: str,
) -> RectificationRecord:
    if requester.role != PartyRole.CONTRACTOR:
        raise HTTPException(status_code=403, detail="仅施工总承包可申请复核")
    if rect.status not in (RectificationStatus.IN_PROGRESS, RectificationStatus.PENDING):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {rect.status.value} 不允许申请复核",
        )
    rect.status = RectificationStatus.RESUBMITTED
    rect.result_note = result_note
    rect.submitted_at = datetime.now()
    return rect


# ---------------------------------------------------------------------------
# 维护周期建议（行业标准映射：按构件规格 + 施工部位 + 最近一次维护发现）
# ---------------------------------------------------------------------------
# 行业经验值（GB 50204 / JGJ 1 等装配式相关规范的运维期建议天数）
_BASE_CYCLE_DAYS = {
    "外墙板": 180,    # 重点关注防水、连接节点
    "内墙板": 365,
    "楼梯": 365,
    "叠合楼板": 365,
    "预制梁": 365,
    "预制柱": 365,
    "预制阳台": 180,  # 悬挑构件，关注防水
    "整体卫浴": 90,   # 防水 / 给排水重点
}

_FINDING_FACTOR = {
    MaintenanceFinding.NORMAL: 1.0,
    MaintenanceFinding.MINOR: 0.6,   # 轻微异常 → 提前 40% 检查
    MaintenanceFinding.MAJOR: 0.3,   # 严重异常 → 大幅提前
}

_LOCATION_FACTOR = {
    "屋面": 0.6, "外墙": 0.7, "卫生间": 0.6, "厨房": 0.7,
}  # 越靠外露、潮湿，频次越密


def suggest_maintenance_cycle(db: Session, component: Component) -> dict:
    """根据构件规格 + 施工部位 + 最近一次维护发现，输出维护周期建议。"""
    base = _BASE_CYCLE_DAYS.get(component.component_type.value, 365)

    # 位置调整：优先看 ComponentLocation.building / floor，其次施工部位备注
    location_text = ""
    loc = db.query(ComponentLocation).filter(ComponentLocation.component_id == component.id).first()
    if loc:
        location_text = f"{loc.building} {loc.floor}"
    for key, factor in _LOCATION_FACTOR.items():
        if key in location_text:
            base = int(base * factor)
            break

    # 最近一次维护发现 → 缩短 / 拉长周期
    last_check = (
        db.query(MaintenanceCheckRecord)
        .filter(MaintenanceCheckRecord.component_id == component.id)
        .order_by(MaintenanceCheckRecord.checked_at.desc(), MaintenanceCheckRecord.id.desc())
        .first()
    )
    finding = last_check.finding if last_check else None
    factor = _FINDING_FACTOR.get(finding, 1.0)
    suggested = max(30, int(base * factor))

    next_at = None
    if last_check:
        next_at = last_check.checked_at + timedelta(days=suggested)
    else:
        # 首次建议：从档案归档后开始算
        arch = db.query(ArchivePackage).filter(ArchivePackage.component_id == component.id).first()
        anchor = arch.created_at if arch else datetime.now()
        next_at = anchor + timedelta(days=suggested)

    risk = "low"
    rationale_parts = [f"按构件类型「{component.component_type.value}」基础周期 {base} 天"]
    if factor != 1.0:
        rationale_parts.append(f"最近发现「{finding.value}」按 {factor} 系数调整")
        risk = "high" if finding == MaintenanceFinding.MAJOR else "medium"
    if location_text:
        rationale_parts.append(f"施工部位 {location_text}")

    return {
        "component_id": component.id,
        "current_finding": finding,
        "suggested_cycle_days": suggested,
        "next_check_at": next_at,
        "rationale": "；".join(rationale_parts),
        "risk_level": risk,
    }


# ---------------------------------------------------------------------------
# 项目进度聚合（甘特 / 看板 / 地图共享数据源）
# ---------------------------------------------------------------------------
_STAGE_RANK_FOR_PROGRESS = {
    "已生产": 1, "出厂": 2, "运输中": 3, "已到场": 4, "已进场": 5,
    "进场不合格": 5, "已吊装": 6, "节点连接": 7, "已隐蔽": 8,
    "成品保护": 9, "已归档": 10,
}
_PROGRESS_TOTAL = max(_STAGE_RANK_FOR_PROGRESS.values())


def aggregate_project_progress(db: Session, project: Project) -> dict:
    """三视图共享的数据：按 stage 桶 + 节点 + 坐标聚合。"""
    components = (
        db.query(Component)
        .filter(Component.project_id == project.id)
        .all()
    )
    total = len(components)
    stage_buckets: Dict[str, int] = {}
    rank_sum = 0
    blocked_components = 0
    for c in components:
        stage_buckets[c.current_stage] = stage_buckets.get(c.current_stage, 0) + 1
        rank_sum += _STAGE_RANK_FOR_PROGRESS.get(c.current_stage, 0)
        if c.current_stage in ("进场不合格",):
            blocked_components += 1
        # 抽检阻断判定
        try:
            if has_blocking_inspection(db, c.id, "已吊装"):
                blocked_components += 1
        except Exception:  # noqa: BLE001
            pass

    overall_pct = round((rank_sum / max(total, 1) / _PROGRESS_TOTAL) * 100, 1)

    # 节点进度
    milestones = (
        db.query(ProjectMilestone)
        .filter(ProjectMilestone.project_id == project.id)
        .order_by(ProjectMilestone.sort_no.asc(), ProjectMilestone.id.asc())
        .all()
    )
    milestone_progress: List[dict] = []
    for m in milestones:
        # 节点对应工序下所有构件完成数
        stage_components = [c for c in components if c.current_stage == m.stage]
        if not stage_components:
            # 按 rank 推进：当所有构件 rank >= m.rank 时认为已达成
            m_rank = _STAGE_RANK_FOR_PROGRESS.get(m.stage, 0)
            completed = sum(
                1 for c in components
                if _STAGE_RANK_FOR_PROGRESS.get(c.current_stage, 0) >= m_rank
            )
            pct = round(completed / max(total, 1) * 100, 1)
            if pct >= 100:
                status = ProjectNodeStatus.ACHIEVED
                actual = datetime.now()
            elif pct > 0:
                status = ProjectNodeStatus.ON_TRACK
                actual = None
            else:
                status = ProjectNodeStatus.PENDING
                actual = None
            blocked = 0
        else:
            completed = len(stage_components)
            pct = round(completed / max(total, 1) * 100, 1)
            status = ProjectNodeStatus.ACHIEVED
            actual = datetime.now()
            blocked = 0

        milestone_progress.append({
            "milestone": m,
            "status": status,
            "actual_at": actual,
            "progress_pct": pct,
            "blocked_components": blocked,
        })

    # 整改 / 抽检未闭环统计
    rect_open = (
        db.query(RectificationRecord)
        .join(QualityInspectionTask, RectificationRecord.task_id == QualityInspectionTask.id)
        .filter(
            QualityInspectionTask.project_id == project.id,
            RectificationRecord.status != RectificationStatus.CLOSED,
        )
        .count()
    )
    inspection_open = (
        db.query(QualityInspectionTask)
        .filter(
            QualityInspectionTask.project_id == project.id,
            QualityInspectionTask.is_closed.is_(False),
        )
        .count()
    )

    # 地图坐标
    locations = (
        db.query(ComponentLocation)
        .filter(ComponentLocation.project_id == project.id)
        .all()
    )

    return {
        "project_id": project.id,
        "project_name": project.name,
        "overall_pct": overall_pct,
        "stage_buckets": stage_buckets,
        "blocked_components": blocked_components,
        "rect_open": rect_open,
        "inspection_open": inspection_open,
        "milestones": milestone_progress,
        "locations": locations,
    }
