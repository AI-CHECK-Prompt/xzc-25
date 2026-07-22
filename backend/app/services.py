"""服务层：业务聚合。"""
from __future__ import annotations

import io
import json
import math
import os
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    AcceptanceResult,
    ArchivePackage,
    ArchiveStatus,
    Component,
    ConcealedAcceptance,
    FactoryOutRecord,
    HoistingRecord,
    JointConnection,
    Party,
    PartyRole,
    Project,
    ProtectionRecord,
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
