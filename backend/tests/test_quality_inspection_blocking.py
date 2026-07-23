"""离线回归：质监抽检 → 阻断 → 整改 → 复核 → 解锁。

场景：
  1) 质监发起抽检任务（工序=已进场）
  2) 抽检录入不合格 → 自动开整改
  3) 吊装被阻断
  4) 施工方提交整改 → 申请复核
  5) 第二名质监员复核 → 失败（必须原抽检人）
  6) 原抽检人复核合格 → 任务闭环，吊装允许
  7) 维护检查 + 周期建议
  8) 项目进度聚合

无 PostgreSQL / Docker 依赖，SQLite 内存库 + 直接调用 services。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as appdb
from app.db import Base
from app.models import (
    AcceptanceResult,
    Component,
    ComponentLocation,
    ComponentType,
    InspectionConclusion,
    MaintenanceFinding,
    Party,
    PartyRole,
    Project,
    ProjectMilestone,
    RectificationStatus,
    SiteEntryRecord,
    User,
)
from app.services import (
    aggregate_project_progress,
    create_inspection_task,
    has_blocking_inspection,
    resubmit_rectification,
    submit_inspection_record,
    submit_rectification,
    suggest_maintenance_cycle,
)

USER_DUMMY_HASH = "x" * 60
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class _Scope:
    def __enter__(self):
        self.s = TestingSession()
        return self.s

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.s.rollback()
        else:
            self.s.commit()
        self.s.close()


appdb.session_scope = _Scope  # type: ignore[assignment]
appdb.engine = engine  # type: ignore[assignment]


def _seed(run_id: str) -> dict:
    with _Scope() as db:
        factory = Party(code=f"F-{run_id}", name=f"工厂-{run_id}", role=PartyRole.FACTORY)
        owner = Party(code=f"O-{run_id}", name=f"业主-{run_id}", role=PartyRole.OWNER)
        contractor = Party(code=f"C-{run_id}", name=f"施工-{run_id}", role=PartyRole.CONTRACTOR)
        quality = Party(code=f"Q-{run_id}", name=f"质监-{run_id}", role=PartyRole.QUALITY)
        db.add_all([factory, owner, contractor, quality])
        db.flush()

        proj = Project(
            code=f"P-{run_id}", name=f"项目-{run_id}",
            owner_party_id=owner.id, contractor_party_id=contractor.id,
            supervisor_party_id=owner.id, start_date=datetime.now(),
        )
        db.add(proj)
        db.flush()

        comp = Component(
            trace_code=f"PC-{run_id}-0001",
            rfid_tag=f"RFID-{run_id}-0001",
            project_id=proj.id, factory_id=factory.id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec="标准外墙 3.6m", quantity=1, current_stage="已进场",
        )
        db.add(comp)
        db.flush()

        site = SiteEntryRecord(
            component_id=comp.id, contractor_id=contractor.id,
            entered_at=datetime.now(), stack_location="A-01",
            inspector="王工", acceptance=AcceptanceResult.PASSED,
        )
        db.add(site)
        db.flush()

        # 给施工方加一个坐标，方便维护建议里"位置"信息生效
        loc = ComponentLocation(
            component_id=comp.id, project_id=proj.id,
            longitude=120.0, latitude=30.0,
            building="1号楼", floor="3F 外墙",
        )
        db.add(loc)
        db.flush()

        q1 = User(
            username=f"q1_{run_id.lower()}", password_hash=USER_DUMMY_HASH,
            full_name="质监员1", role=PartyRole.QUALITY, party_id=quality.id,
        )
        q2 = User(
            username=f"q2_{run_id.lower()}", password_hash=USER_DUMMY_HASH,
            full_name="质监员2", role=PartyRole.QUALITY, party_id=quality.id,
        )
        cu = User(
            username=f"cu_{run_id.lower()}", password_hash=USER_DUMMY_HASH,
            full_name="施工员", role=PartyRole.CONTRACTOR, party_id=contractor.id,
        )
        db.add_all([q1, q2, cu])
        db.flush()

        # 节点
        for code, name, stage, sn in [
            ("P1", "生产完成", "成品保护", 0),
            ("P2", "运输完成", "已卸货", 1),
            ("P3", "进场完成", "已进场", 2),
            ("P4", "吊装完成", "已吊装", 3),
            ("P5", "档案归档", "已归档", 4),
        ]:
            db.add(ProjectMilestone(
                project_id=proj.id, code=code, name=name, stage=stage, sort_no=sn,
            ))

        return {
            "run_id": run_id, "proj_id": proj.id, "comp_id": comp.id,
            "q1_id": q1.id, "q2_id": q2.id, "cu_id": cu.id,
            "contractor_party_id": contractor.id,
        }


def main() -> int:
    failures: list[str] = []
    print("== 准备：质监抽检 → 阻断 → 整改 → 复核 → 解锁 ==\n")
    f = _seed("INS")
    run_id = f["run_id"]

    def fail(msg: str):
        print(f"  [FAIL] {msg}")
        failures.append(msg)

    def ok(msg: str):
        print(f"  [OK] {msg}")

    # 1) 质监发起抽检任务
    with _Scope() as db:
        comp = db.get(Component, f["comp_id"])
        q1 = db.get(User, f["q1_id"])
        task = create_inspection_task(
            db, comp, q1, "已进场", "进场抽检",
            "外观 / 尺寸 / 强度报告", datetime.now(), inspector_user_id=f["q1_id"],
        )
        task_id = task.id

    # 2) 录入不合格抽检 → 自动开整改
    with _Scope() as db:
        task = db.get(type(task), task_id)
        rec, rect = submit_inspection_record(
            db, task, q1, datetime.now(), "工地A-01",
            InspectionConclusion.UNPASSED,
            findings="外观裂缝 > 0.3mm",
            measures="要求打磨修补并复测", photo_urls=[], is_reinspection=False,
        )
        rect_id = rect.id if rect else None

    if rect_id is None:
        fail("不合格抽检未自动开整改")
    else:
        ok("不合格抽检自动开整改")

    # 3) 验证 has_blocking_inspection → 吊装应被阻断
    with _Scope() as db:
        comp = db.get(Component, f["comp_id"])
        if has_blocking_inspection(db, comp.id, "已吊装"):
            ok("吊装被未闭环抽检阻断")
        else:
            fail("吊装未被阻断（has_blocking_inspection=False）")

    # 4) 施工方提交整改 → 申请复核
    with _Scope() as db:
        from app.models import RectificationRecord
        rect = db.get(RectificationRecord, rect_id)
        cu = db.get(User, f["cu_id"])
        submit_rectification(
            db, rect, cu,
            plan="表面打磨 + 聚合物砂浆修补",
            progress_note="已联系修补班组进场",
            photo_urls=[], deadline=datetime.now() + timedelta(days=3),
        )
        resubmit_rectification(db, rect, cu, "现场已整改完成，请复核")

    with _Scope() as db:
        from app.models import RectificationRecord as RR
        rect = db.get(RR, rect_id)
        if rect.status == RectificationStatus.RESUBMITTED:
            ok("整改单状态推进到「已申请复核」")
        else:
            fail(f"整改单状态错误：{rect.status}")

    # 5) 第二名质监员复核 → 失败（必须原抽检人）
    with _Scope() as db:
        task = db.get(QualityInspectionTask := __import__("app.models", fromlist=["QualityInspectionTask"]).QualityInspectionTask, task_id)
        q2 = db.get(User, f["q2_id"])
        try:
            submit_inspection_record(
                db, task, q2, datetime.now(), "工地A-01",
                InspectionConclusion.RECTIFIED,
                findings="—", measures="—", photo_urls=[],
                is_reinspection=True,
            )
            fail("第二名质监员复核未被拒绝（应只允许原抽检人）")
        except Exception as exc:  # noqa: BLE001
            if "原抽检人" in str(exc) or "复核" in str(exc):
                ok("第二名质监员复核被拒绝（仅原抽检人可复核）")
            else:
                fail(f"复核失败但异常信息不符预期：{exc!r}")

    # 6) 原抽检人复核合格 → 任务闭环 + 吊装解锁
    with _Scope() as db:
        from app.models import QualityInspectionTask as QIT
        task = db.get(QIT, task_id)
        q1 = db.get(User, f["q1_id"])
        submit_inspection_record(
            db, task, q1, datetime.now(), "工地A-01",
            InspectionConclusion.RECTIFIED,
            findings="修补后复测合格", measures="—", photo_urls=[],
            is_reinspection=True,
        )

    with _Scope() as db:
        from app.models import QualityInspectionTask as QIT
        task = db.get(QIT, task_id)
        if task.is_closed:
            ok("原抽检人复核后任务闭环")
        else:
            fail("任务未闭环")

    with _Scope() as db:
        comp = db.get(Component, f["comp_id"])
        if not has_blocking_inspection(db, comp.id, "已吊装"):
            ok("吊装阻断已解除")
        else:
            fail("吊装仍被阻断")

    # 7) 维护建议：基础周期 = 180天 (外墙板)，位置 = 外墙 → 0.7 系数 = 126 天
    with _Scope() as db:
        from app.models import MaintenanceCheckRecord
        comp = db.get(Component, f["comp_id"])
        # 先登记一次"正常"维护
        rec = MaintenanceCheckRecord(
            component_id=comp.id, project_id=f["proj_id"],
            operator_party_id=f["contractor_party_id"], operator_user_id=f["cu_id"],
            checked_at=datetime.now(), finding=MaintenanceFinding.NORMAL,
            description="外观无异常", action_taken="—", next_check_in_days=0,
        )
        db.add(rec)
        advice = suggest_maintenance_cycle(db, comp)

    expected_base = 180
    expected_after = int(180 * 0.7)  # 126
    if advice["suggested_cycle_days"] == expected_after and advice["risk_level"] == "low":
        ok(f"维护建议 {expected_after} 天 (基础 {expected_base} × 外墙系数 0.7)，风险=低")
    else:
        fail(f"维护建议 {advice['suggested_cycle_days']} 天，风险 {advice['risk_level']}")

    # 严重异常场景：风险升级
    with _Scope() as db:
        from app.models import MaintenanceCheckRecord
        comp = db.get(Component, f["comp_id"])
        rec = MaintenanceCheckRecord(
            component_id=comp.id, project_id=f["proj_id"],
            operator_party_id=f["contractor_party_id"], operator_user_id=f["cu_id"],
            checked_at=datetime.now() + timedelta(days=1),  # 比前一次晚，确保排序稳定
            finding=MaintenanceFinding.MAJOR,
            description="接缝处渗水", action_taken="—", next_check_in_days=0,
        )
        db.add(rec)
        db.flush()  # autoflush=False，必须显式 flush 后建议函数才能看到
        advice2 = suggest_maintenance_cycle(db, comp)
    if advice2["risk_level"] == "high" and advice2["suggested_cycle_days"] < 60:
        ok(f"严重异常场景：建议 {advice2['suggested_cycle_days']} 天，风险=高")
    else:
        fail(f"严重异常场景：{advice2}")

    # 8) 项目进度聚合
    with _Scope() as db:
        proj = db.get(Project, f["proj_id"])
        data = aggregate_project_progress(db, proj)
    if data["blocked_components"] == 0 and data["overall_pct"] > 0 and data["milestones"]:
        ok(f"项目进度：整体 {data['overall_pct']}%，节点 {len(data['milestones'])} 个，被阻断 {data['blocked_components']} 个")
    else:
        fail(f"项目进度数据异常：{data}")

    if failures:
        for f in failures:
            print(f"\n{f}")
        return 1
    print("\n[OK] 全部抽检 / 整改 / 维护 / 进度 回归用例通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
