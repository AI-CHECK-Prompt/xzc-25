"""离线回归：build_trace 对多类型告警的拆分展示。

本环境无 PostgreSQL / Docker，于是用 SQLite 内存库构造同样的业务数据，
直接调用修改后的 build_trace() 函数，验证：
  1) summary 字段不再含「告警」拼接
  2) 同一 telemetry 上的 TEMP_OUT + OFF_ROUTE 两条告警都出现在 extras.alerts
  3) extras.alerts 中两条告警的 alert_type 不同（运营可一眼区分）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

# 切到 SQLite 内存库 + 调整 database_url，避免依赖 PostgreSQL
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 在 import 任何 app.* 之前先准备好 engine，并 monkey-patch db.engine
import app.db as appdb  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import (  # noqa: E402
    AcceptanceResult,
    Component,
    ComponentType,
    FactoryOutRecord,
    Party,
    PartyRole,
    Project,
    TransportAlert,
    TransportStatus,
    TransportTelemetry,
    User,
)
from app.services import build_trace  # noqa: E402
# 这里不真正调用 hash_password，避免本地 bcrypt 兼容性问题；
# build_trace 不会校验密码哈希，任意占位字符串均可
USER_DUMMY_HASH = "x" * 60

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
# 让 app.session_scope() 用我们自己的 engine
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class _Scope:
    def __enter__(self):
        self.s = TestingSession()
        return self.s

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.s.rollback()
        else:
            self.s.commit()  # 关键：默认提交，让下一个 session 看到数据
        self.s.close()


appdb.session_scope = _Scope  # type: ignore[assignment]
appdb.engine = engine  # type: ignore[assignment]


def _seed():
    with _Scope() as db:
        factory = Party(code="FACTORY01", name="工厂", role=PartyRole.FACTORY,
                        contact="", address="")
        transport = Party(code="TRANSPORT01", name="运输", role=PartyRole.TRANSPORT,
                          contact="", address="")
        owner = Party(code="OWNER01", name="业主", role=PartyRole.OWNER,
                      contact="", address="")
        db.add_all([factory, transport, owner])
        db.flush()

        proj = Project(code="PRJ-TEST", name="测试项目", location="",
                       description="",
                       owner_party_id=owner.id,
                       contractor_party_id=owner.id,
                       supervisor_party_id=owner.id,
                       start_date=datetime.now())
        db.add(proj)
        db.flush()

        comp = Component(
            trace_code="PC-TEST-0001",
            rfid_tag="RFID-TEST-0001",
            project_id=proj.id,
            factory_id=factory.id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec="TEST",
            quantity=1,
            current_stage="运输中",
        )
        db.add(comp)
        db.flush()

        out = FactoryOutRecord(
            component_id=comp.id,
            factory_id=factory.id,
            transport_party_id=transport.id,
            out_at=datetime.now(),
            vehicle_no="V-001",
            driver="张师傅",
            inspection_conclusion=AcceptanceResult.PASSED,
        )
        db.add(out)
        db.flush()

        # 单条遥测，温度 80℃ 触发温度越界；同 telemetry 再手工补一条偏离路线告警
        tel = TransportTelemetry(
            component_id=comp.id,
            transport_record_id=out.id,
            reported_at=datetime.now(),
            longitude=120.0,
            latitude=30.0,
            temperature=80.0,
            humidity=40.0,
            status=TransportStatus.IN_TRANSIT,
        )
        db.add(tel)
        db.flush()

        # 两条不同类型告警挂在同一条 telemetry 上 —— 复现事故现场
        db.add(TransportAlert(
            component_id=comp.id,
            telemetry_id=tel.id,
            alert_type="TEMP_OUT",
            detail="温湿度越界：温度 80.0℃、湿度 40.0%RH",
            resolved=False,
        ))
        db.add(TransportAlert(
            component_id=comp.id,
            telemetry_id=tel.id,
            alert_type="OFF_ROUTE",
            detail="相邻两点距离 5.3km，疑似偏离路线",
            resolved=False,
        ))

        owner_user = User(
            username="owner01",
            password_hash=USER_DUMMY_HASH,
            full_name="业主",
            role=PartyRole.OWNER,
            party_id=owner.id,
        )
        db.add(owner_user)


def main() -> int:
    _seed()
    with _Scope() as db:
        owner = db.query(User).filter(User.username == "owner01").first()
        resp = build_trace(db, "PC-TEST-0001", owner)

    traj = [t for t in resp.timeline if t.stage.startswith("运输轨迹")]
    assert traj, f"未找到运输轨迹步骤：{resp.timeline}"
    step = traj[0]
    summary = step.summary
    extras = step.extras or {}
    alerts = extras.get("alerts") or []

    print(f"summary  : {summary}")
    print(f"alerts   : {alerts}")

    failures = []
    if "告警" in summary or "｜" in summary:
        failures.append(f"summary 仍拼接告警：{summary!r}")
    if len(alerts) != 2:
        failures.append(f"alerts 数量={len(alerts)}，期望 2")
    if {a["alert_type"] for a in alerts} != {"TEMP_OUT", "OFF_ROUTE"}:
        failures.append(f"alerts 类型集合={ {a['alert_type'] for a in alerts} }，期望 TEMP_OUT+OFF_ROUTE")
    if any(not a.get("detail") for a in alerts):
        failures.append("有告警缺失 detail")

    if failures:
        for f in failures:
            print("[FAIL]", f)
        return 1
    print("\n[OK] 同一遥测点 TEMP_OUT + OFF_ROUTE 两条告警已各自独立出现在 extras.alerts，"
          "summary 不再混入告警文本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
