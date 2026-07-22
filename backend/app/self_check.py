"""四类追溯验收场景的自检脚本。

执行：
  docker compose exec backend python -m app.self_check
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Callable, List, Tuple

from .auth import create_access_token
from .db import session_scope
from .models import (
    AcceptanceResult,
    ArchivePackage,
    ArchiveStatus,
    Component,
    ComponentType,
    ConcealedAcceptance,
    ConnectionType,
    FactoryOutRecord,
    HoistResult,
    HoistingRecord,
    JointConnection,
    Party,
    PartyRole,
    Project,
    ProtectionRecord,
    SiteEntryRecord,
    User,
)


PASS = "\033[92m PASS \033[0m"
FAIL = "\033[91m FAIL \033[0m"
INFO = "\033[96m INFO \033[0m"


def _print(ok: bool, scenario: str, detail: str) -> None:
    tag = PASS if ok else FAIL
    print(f"[{tag}] {scenario} | {detail}")


def _login(db, username: str) -> str:
    user: User | None = db.query(User).filter(User.username == username).first()
    if not user:
        raise RuntimeError(f"缺少默认用户 {username}")
    return create_access_token(sub=user.username, role=user.role.value, party_id=user.party_id)


def _ensure_demo_data(db) -> Tuple[Component, Component]:
    """若全链路示例数据不存在，则为阳光城A区一标段补建 1 个合格件 + 1 个不合格件。"""
    project = db.query(Project).filter(Project.code == "PRJ-SUN-001").first()
    if not project:
        raise RuntimeError("缺少示例项目 PRJ-SUN-001，请先启动后端完成 bootstrap")

    factory = db.query(Party).filter(Party.role == PartyRole.FACTORY).first()
    transport = db.query(Party).filter(Party.role == PartyRole.TRANSPORT).first()
    contractor = db.query(Party).filter(Party.role == PartyRole.CONTRACTOR).first()
    supervisor = db.query(Party).filter(Party.role == PartyRole.SUPERVISOR).first()

    now = datetime.now()
    components: List[Component] = []

    def _build_component(suffix: str, accepted: bool) -> Component:
        comp = Component(
            project_id=project.id,
            factory_id=factory.id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec=f"YGW-外墙板-3.0m×6.0m-{suffix}",
            mould_no=f"M-{suffix}",
            rebar_batch=f"RB-2025-{suffix}",
            concrete_ratio="C40",
            pour_at=now - timedelta(days=14),
            curing_record="标准养护 14 天，温湿度记录完整",
            strength_report=f"STR-2025-{suffix}",
            embedded_parts={"吊点": 4, "电气盒": 2, "灌浆套筒": 6},
            factory_inspection=AcceptanceResult.PASSED,
            current_stage="已生产",
        )
        comp.trace_code = f"PC-DEMO-{suffix}"
        comp.rfid_tag = f"RFID-DEMO-{suffix}"
        comp.qr_payload = f"http://localhost:5173/trace?code={comp.trace_code}"
        db.add(comp)
        db.flush()
        return comp

    passed = db.query(Component).filter(Component.trace_code == "PC-DEMO-PASS").first()
    if not passed:
        passed = _build_component("PASS", accepted=True)
    unpassed = db.query(Component).filter(Component.trace_code == "PC-DEMO-FAIL").first()
    if not unpassed:
        unpassed = _build_component("FAIL", accepted=False)
    db.commit()
    components.extend([passed, unpassed])

    # 完整补齐 PASS 构件全链路
    if not db.query(FactoryOutRecord).filter(FactoryOutRecord.component_id == passed.id).first():
        db.add(
            FactoryOutRecord(
                component_id=passed.id,
                factory_id=factory.id,
                transport_party_id=transport.id,
                out_at=now - timedelta(days=10),
                vehicle_no="苏A·12345",
                driver="张师傅",
                route_plan="南京工厂 → 杭州阳光城A区工地",
                inspection_conclusion=AcceptanceResult.PASSED,
            )
        )
        passed.current_stage = "运输中"
    if not db.query(SiteEntryRecord).filter(SiteEntryRecord.component_id == passed.id).first():
        db.add(
            SiteEntryRecord(
                component_id=passed.id,
                contractor_id=contractor.id,
                entered_at=now - timedelta(days=8),
                stack_location="A区堆场B3-12",
                inspector="王工",
                acceptance=AcceptanceResult.PASSED,
            )
        )
        passed.current_stage = "已进场"
    if not db.query(HoistingRecord).filter(HoistingRecord.component_id == passed.id).first():
        db.add(
            HoistingRecord(
                component_id=passed.id,
                contractor_id=contractor.id,
                hoisted_at=now - timedelta(days=6),
                equipment_no="TC7032",
                signal_worker="李工",
                rigger="赵师傅",
                coord_lng=119.965,
                coord_lat=30.276,
                result=HoistResult.SUCCESS,
            )
        )
        passed.current_stage = "已吊装"
    if not db.query(JointConnection).filter(JointConnection.component_id == passed.id).first():
        db.add(
            JointConnection(
                component_id=passed.id,
                contractor_id=contractor.id,
                grout_at=now - timedelta(days=5),
                grout_batch="GB-2025-001",
                bedding_at=now - timedelta(days=5, hours=-2),
                connection_type=ConnectionType.GROUT_SLEEVE,
                operator="孙师傅",
            )
        )
        passed.current_stage = "节点连接"
    if not db.query(ConcealedAcceptance).filter(ConcealedAcceptance.component_id == passed.id).first():
        db.add(
            ConcealedAcceptance(
                component_id=passed.id,
                supervisor_id=supervisor.id,
                accepted_at=now - timedelta(days=4),
                quality_grade="合格",
                inspector="刘监理",
                conclusion="灌浆饱满、套筒连接到位",
            )
        )
        passed.current_stage = "已隐蔽"
    if not db.query(ProtectionRecord).filter(ProtectionRecord.component_id == passed.id).first():
        db.add(
            ProtectionRecord(
                component_id=passed.id,
                contractor_id=contractor.id,
                decoration="待装饰",
                mep="待机电",
                measures="已贴保护膜",
                risk_warning="",
            )
        )
        passed.current_stage = "成品保护"

    # FAIL 件只到进场，且不合格
    if not db.query(SiteEntryRecord).filter(SiteEntryRecord.component_id == unpassed.id).first():
        db.add(
            SiteEntryRecord(
                component_id=unpassed.id,
                contractor_id=contractor.id,
                entered_at=now - timedelta(days=8),
                stack_location="A区堆场B3-15",
                inspector="王工",
                acceptance=AcceptanceResult.UNPASSED,
                remark="外观破损 3 处",
            )
        )
        unpassed.current_stage = "进场不合格"

    db.commit()
    return passed, unpassed


def scenario_one() -> bool:
    print(f"\n[{INFO}] 场景 1：容器栈启动 + 批量注入完整数据")
    with session_scope() as db:
        parties = db.query(Party).count()
        users = db.query(User).count()
        projects = db.query(Project).count()
        comps = db.query(Component).count()
        ok = parties >= 6 and users >= 6 and projects >= 2 and comps >= 2
        _print(
            ok,
            "场景1",
            f"参与方={parties}, 用户={users}, 项目={projects}, 构件={comps}",
        )
    return ok


def scenario_two() -> bool:
    print(f"\n[{INFO}] 场景 2：追溯查询全链路")
    from .schemas import TraceResponse
    from .services import build_trace

    with session_scope() as db:
        user = db.query(User).filter(User.username == "owner01").first()
        try:
            passed, _ = _ensure_demo_data(db)
            resp = build_trace(db, passed.trace_code, user)
            ok = (
                len(resp.timeline) >= 6
                and any("构件生产" in t.stage for t in resp.timeline)
                and any("构件出厂" in t.stage for t in resp.timeline)
                and any("构件进场" in t.stage for t in resp.timeline)
                and any("构件吊装" in t.stage for t in resp.timeline)
                and any("节点连接" in t.stage for t in resp.timeline)
                and any("隐蔽验收" in t.stage for t in resp.timeline)
            )
            _print(ok, "场景2", f"trace={passed.trace_code}, timeline_steps={len(resp.timeline)}")
            return ok
        except Exception as exc:  # noqa: BLE001
            _print(False, "场景2", f"异常 {exc}")
            return False


def scenario_three() -> bool:
    print(f"\n[{INFO}] 场景 3：不合格件禁止吊装")
    from fastapi import HTTPException
    from .routes.site import hoist

    with session_scope() as db:
        try:
            _, unpassed = _ensure_demo_data(db)
            contractor_user = db.query(User).filter(User.username == "contractor01").first()
            class _Body:
                component_id = unpassed.id
                hoisted_at = datetime.now()
                equipment_no = "TC9999"
                signal_worker = "X"
                rigger = "Y"
                coord_lng = 0.0
                coord_lat = 0.0
                result = HoistResult.SUCCESS
            try:
                hoist(_Body(), db=db, user=contractor_user)  # type: ignore[arg-type]
                _print(False, "场景3", "未抛出异常，吊装校验失败")
                return False
            except HTTPException as e:
                ok = e.status_code == 409 and "禁止进入吊装流程" in (e.detail or "")
                _print(ok, "场景3", f"HTTP {e.status_code}: {e.detail}")
                return ok
        except Exception as exc:  # noqa: BLE001
            _print(False, "场景3", f"异常 {exc}")
            return False


def scenario_four() -> bool:
    print(f"\n[{INFO}] 场景 4：档案归档导出与报送")
    import os
    from .services import generate_archive

    with session_scope() as db:
        try:
            passed, _ = _ensure_demo_data(db)
            owner = db.query(User).filter(User.username == "owner01").first()
            archive = generate_archive(db, passed, owner)
            db.commit()
            file_exists = os.path.exists(archive.file_path)
            archive_ok = (
                archive.status in (ArchiveStatus.GENERATED, ArchiveStatus.SUBMITTED)
                and file_exists
            )
            _print(
                archive_ok,
                "场景4",
                f"archive_no={archive.archive_no}, file={archive.file_path}, exists={file_exists}",
            )
            return archive_ok
        except Exception as exc:  # noqa: BLE001
            _print(False, "场景4", f"异常 {exc}")
            return False


def main() -> int:
    results = [
        scenario_one(),
        scenario_two(),
        scenario_three(),
        scenario_four(),
    ]
    print("\n============================================")
    print(f" 自检汇总：通过 {sum(results)}/{len(results)}")
    print("============================================")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
