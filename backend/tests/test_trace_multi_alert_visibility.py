"""追溯详情页：运输告警多类型独立展示 —— 回归用例。

场景还原（运营事故）：
  某次运输过程中温度短暂飙升至 80℃（超过 60℃ 阈值），同时因高速行驶产生
  位置跳变触发「偏离路线」告警。原实现将「告警」文本与运输轨迹拼接在同一行
  summary 字段，运营人员无法快速判断构件当前究竟是温度越界还是位置偏离。

修复期望（位于 backend/app/services.py build_trace）：
  1) summary 字段只承载轨迹本体（位置/温湿度/状态），不再拼接「｜告警 …」。
  2) 同一 telemetry 上同时存在的多条不同类型告警，必须全部独立出现在
     extras.alerts 列表中（不能只取第一条）。
  3) 详情页可通过 extras.alerts 渲染出可区分的告警卡片（温度越界 vs 偏离路线）。

使用方法：
  1) 启动后端：cd backend && uvicorn app.main:app --port 8000
  2) cd backend && python tests/test_trace_multi_alert_visibility.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta

import requests
from sqlalchemy import delete

# 允许以 `python tests/test_xxx.py` 直接运行
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import session_scope  # noqa: E402
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
)

BASE = "http://localhost:8000"
# 使用 owner01（业主方）—— 业主方对追溯详情有完整查看权限（can_view_full=True）
OWNER_USER = "owner01"
OWNER_PASS = "123456"

RUN_ID = uuid.uuid4().hex[:8]


def _setup_fixture() -> dict:
    """直接落库：1 个构件 + 1 条出厂记录 + 1 条遥测 + 2 条不同类型告警。

    两类告警指向同一条 telemetry，复现「同一时刻多告警」的真实事故场景。
    """
    with session_scope() as db:
        proj = db.query(Project).filter(Project.code == "PRJ-SUN-001").first()
        if not proj:
            raise SystemExit("种子项目 PRJ-SUN-001 不存在，请先启动一次后端完成 bootstrap")
        factory = db.query(Party).filter(Party.code == "FACTORY01").first()
        transport = db.query(Party).filter(Party.code == "TRANSPORT01").first()
        if not (factory and transport):
            raise SystemExit("种子参与方 FACTORY01 / TRANSPORT01 缺失")

        trace_code = f"PC-ALERT-{RUN_ID}-0001"
        comp = Component(
            trace_code=trace_code,
            rfid_tag=f"RFID-ALERT-{RUN_ID}-0001",
            project_id=proj.id,
            factory_id=factory.id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec=f"ALERT-{RUN_ID}",
            quantity=1,
            current_stage="运输中",
        )
        db.add(comp)
        db.flush()

        out_rec = FactoryOutRecord(
            component_id=comp.id,
            factory_id=factory.id,
            transport_party_id=transport.id,
            out_at=datetime.now() - timedelta(minutes=10),
            vehicle_no=f"V-{RUN_ID}",
            driver="测试司机",
            inspection_conclusion=AcceptanceResult.PASSED,
        )
        db.add(out_rec)
        db.flush()

        # 单条遥测：温度 80℃（>60 阈值）+ 位置 (0, 0)，为触发告警构造数据
        now = datetime.now()
        tel = TransportTelemetry(
            component_id=comp.id,
            transport_record_id=out_rec.id,
            reported_at=now,
            longitude=0.0,
            latitude=0.0,
            temperature=80.0,
            humidity=40.0,
            status=TransportStatus.IN_TRANSIT,
        )
        db.add(tel)
        db.flush()

        # 关键：两条不同类型的告警挂在同一条 telemetry 上
        # 复现「温度飙升至 80℃」+「高速行驶产生位置跳变」同时发生的场景
        a_temp = TransportAlert(
            component_id=comp.id,
            telemetry_id=tel.id,
            alert_type="TEMP_OUT",
            detail="温湿度越界：温度 80.0℃、湿度 40.0%RH",
            resolved=False,
        )
        a_route = TransportAlert(
            component_id=comp.id,
            telemetry_id=tel.id,
            alert_type="OFF_ROUTE",
            detail="相邻两点距离 5.3km，疑似偏离路线",
            resolved=False,
        )
        db.add(a_temp)
        db.add(a_route)
        db.flush()

        return {
            "component_id": comp.id,
            "out_record_id": out_rec.id,
            "telemetry_id": tel.id,
            "alert_temp_id": a_temp.id,
            "alert_route_id": a_route.id,
            "trace_code": trace_code,
        }


def _cleanup(fix: dict) -> None:
    with session_scope() as db:
        db.execute(delete(TransportAlert).where(
            TransportAlert.id.in_([fix["alert_temp_id"], fix["alert_route_id"]])
        ))
        db.execute(delete(TransportTelemetry).where(
            TransportTelemetry.id == fix["telemetry_id"]
        ))
        db.execute(delete(FactoryOutRecord).where(
            FactoryOutRecord.id == fix["out_record_id"]
        ))
        db.execute(delete(Component).where(Component.id == fix["component_id"]))


def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _get_trace(token: str, trace_code: str) -> dict:
    r = requests.get(
        f"{BASE}/api/trace/{trace_code}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    print(f"== run_id={RUN_ID} 准备：单条遥测 + 两条不同类型告警 ==")
    fix = _setup_fixture()
    print(f"  trace_code={fix['trace_code']}")
    print(f"  telemetry_id={fix['telemetry_id']}  alert_temp={fix['alert_temp_id']}  alert_route={fix['alert_route_id']}")

    try:
        print("== owner 登录 ==")
        token = _login(OWNER_USER, OWNER_PASS)

        print("== 调 /api/trace/{code} 拿全链路时间线 ==")
        data = _get_trace(token, fix["trace_code"])
        timeline = data.get("timeline", [])

        # 仅筛选「运输轨迹」步骤（与回归目标强相关）
        traj_steps = [s for s in timeline if s.get("stage", "").startswith("运输轨迹")]
        if not traj_steps:
            print(f"[FAIL] timeline 中未找到运输轨迹步骤，timeline={timeline}")
            return 1
        step = traj_steps[0]
        summary = step.get("summary", "")
        extras = step.get("extras") or {}
        alerts = extras.get("alerts") or []

        print(f"  summary: {summary}")
        print(f"  extras.alerts 数量: {len(alerts)}")
        for a in alerts:
            print(f"    - {a}")

        failures = []

        # ---- 断言 1：summary 不再拼接「告警」 ----
        # 修复前：summary = "位置 ..., 温度 80.0℃ / 湿度 40.0%RH, 状态 运输中｜告警 TEMP_OUT ..."
        # 修复后：summary 仅有轨迹本体，告警信息剥离到 extras.alerts
        if "告警" in summary or "｜" in summary:
            failures.append(
                f"[FAIL] summary 仍包含「告警」拼接：{summary!r}"
                " —— 轨迹与告警未分离，运营人员仍会误判状态"
            )
        else:
            print(f"  [OK] summary 已剥离告警文本：{summary!r}")

        # ---- 断言 2：extras.alerts 携带全部两条告警（不是只取第一条） ----
        if len(alerts) != 2:
            failures.append(
                f"[FAIL] extras.alerts 数量={len(alerts)}，期望 2 条"
                " —— 同一时刻的多条告警被丢失"
            )
        else:
            print("  [OK] extras.alerts 数量为 2，未丢告警")

        # ---- 断言 3：两条告警类型互不相同，运营人员可在前端一眼区分 ----
        types = {a.get("alert_type") for a in alerts}
        if types != {"TEMP_OUT", "OFF_ROUTE"}:
            failures.append(
                f"[FAIL] extras.alerts 告警类型集合={types}，期望 {{'TEMP_OUT','OFF_ROUTE'}}"
                " —— 温度越界与偏离路线必须各自保留为独立告警"
            )
        else:
            print("  [OK] 同时包含 TEMP_OUT 与 OFF_ROUTE 两类独立告警")

        # ---- 断言 4：每条告警都有清晰的 detail 字段，运营可读 ----
        for a in alerts:
            if not a.get("detail"):
                failures.append(
                    f"[FAIL] 告警 {a.get('alert_type')} 缺少 detail，运营无法判断具体异常"
                )
        if all(a.get("detail") for a in alerts):
            print("  [OK] 每条告警均携带 detail")

        # ---- 断言 5：告警信息未泄露到 summary 同行字符串中（与断言 1 互补） ----
        for t in timeline:
            s = t.get("summary", "")
            if "告警" in s or "alert_type" in s:
                failures.append(
                    f"[FAIL] 其他阶段 summary 也混入了告警文本：stage={t.get('stage')} summary={s!r}"
                )
        if not any("告警" in t.get("summary", "") or "alert_type" in t.get("summary", "") for t in timeline):
            print("  [OK] 全链路 summary 均未混入告警文本")

        if failures:
            print("\n".join(failures))
            return 1
        print("\n[OK] 温度越界 / 偏离路线两条告警已独立展示，运营可一眼区分构件当前异常类型。")
        return 0
    finally:
        print("== 清理测试数据 ==")
        _cleanup(fix)


if __name__ == "__main__":
    sys.exit(main())
