"""可吊装构件查询接口 —— 项目隔离回归用例。

场景还原（生产事故）：
  工地 A 的施工总承包账号调用 /api/site/hoisting/eligible 时，返回的列表里
  出现了工地 B 的多条构件（追溯码 / 规格 / 阶段完整可见），施工员扫码吊装
  时被拒收。根因：原实现按全平台 SiteEntryRecord / HoistingRecord 取集合，
  未按 Project.contractor_party_id 做隔离。

修复期望：
  每个施工总承包账号只能看到自己所属项目下的可吊装构件，看不到其他承包方
  / 其他工地的构件（即便对方已进场合格、本方未吊装）。

使用方法：
  1) 启动后端：cd backend && uvicorn app.main:app --port 8000
  2) cd backend && python tests/test_eligible_project_isolation.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from typing import Set

import requests
from sqlalchemy import delete

# 让脚本可以以 `python tests/test_concurrent_trace_code.py` 形式运行
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth import hash_password  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    AcceptanceResult,
    Component,
    ComponentType,
    Party,
    PartyRole,
    Project,
    SiteEntryRecord,
    User,
)

BASE = "http://localhost:8000"
RUN_ID = uuid.uuid4().hex[:8]            # 每次跑测试用不同前缀，避免脏数据互相覆盖
CONTRACTOR_A_USER = "contractor01"        # 种子账号：CONTRACTOR01（阳光城 A/B 区都归他管）
CONTRACTOR_A_PASS = "123456"
CONTRACTOR_B_USER = f"contract_b_{RUN_ID}"  # 临时承包方 B，独占一个项目
CONTRACTOR_B_PASS = "123456"
PROJECT_B_CODE = f"PRJ-ISO-{RUN_ID}"        # 临时项目 B（只有 B 承包）


# ---------------------------------------------------------------------------
# 直接 DB 准备：创建承包方 B + 项目 B + 各 1 个构件 + 进场合格记录
# 后端 API 暂未提供 admin 端建参与方/项目，故此处走 ORM
# ---------------------------------------------------------------------------
def _setup_isolation_fixture():
    """插入承包方 B、项目 B、各 1 个构件 + 进场合格记录。

    返回 (project_a_id, project_b_id, comp_a_id, comp_b_id,
          trace_code_a, trace_code_b, party_b_id)
    """
    with session_scope() as db:
        # 项目 A 必须是已存在的种子项目（PRJ-SUN-001）
        proj_a = db.query(Project).filter(Project.code == "PRJ-SUN-001").first()
        if not proj_a:
            raise SystemExit("种子项目 PRJ-SUN-001 不存在，请先启动一次后端完成 bootstrap")
        party_a = db.query(Party).filter(Party.id == proj_a.contractor_party_id).first()
        if not party_a:
            raise SystemExit("种子承包方 CONTRACTOR01 不存在")

        # 承包方 B
        party_b = Party(
            code=f"CONTRACTOR_B_{RUN_ID}",
            name=f"隔离测试承包方B-{RUN_ID}",
            role=PartyRole.CONTRACTOR,
            contact="",
            address="",
        )
        db.add(party_b)
        db.flush()
        user_b = User(
            username=CONTRACTOR_B_USER,
            password_hash=hash_password(CONTRACTOR_B_PASS),
            full_name="隔离测试B",
            role=PartyRole.CONTRACTOR,
            party_id=party_b.id,
        )
        db.add(user_b)

        # 项目 B（独立工地，只有 B 承包）
        proj_b = Project(
            code=PROJECT_B_CODE,
            name=f"隔离测试工地B-{RUN_ID}",
            location="测试场",
            description="回归用例专用",
            owner_party_id=party_a.id,        # 业主复用 A，省得再 seed 一个 owner
            contractor_party_id=party_b.id,   # 关键：只有 B 是承包方
            supervisor_party_id=party_a.id,   # 监理复用
            start_date=datetime.now(),
        )
        db.add(proj_b)
        db.flush()

        now = datetime.now().isoformat()
        # 项目 A 下加 1 个构件
        comp_a = Component(
            trace_code=f"PC-ISO-A-{RUN_ID}-0001",
            rfid_tag=f"RFID-ISO-A-{RUN_ID}-0001",
            project_id=proj_a.id,
            factory_id=db.query(Party).filter(Party.code == "FACTORY01").first().id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec=f"ISO-A-{RUN_ID}",
            quantity=1,
            current_stage="已进场",
        )
        db.add(comp_a)
        # 项目 B 下加 1 个构件
        comp_b = Component(
            trace_code=f"PC-ISO-B-{RUN_ID}-0001",
            rfid_tag=f"RFID-ISO-B-{RUN_ID}-0001",
            project_id=proj_b.id,
            factory_id=db.query(Party).filter(Party.code == "FACTORY01").first().id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec=f"ISO-B-{RUN_ID}",
            quantity=1,
            current_stage="已进场",
        )
        db.add(comp_b)
        db.flush()

        # 双方各自做一次合格进场登记
        db.add(SiteEntryRecord(
            component_id=comp_a.id,
            contractor_id=party_a.id,
            entered_at=datetime.now(),
            stack_location=f"A区-{RUN_ID}",
            inspector="测试员A",
            acceptance=AcceptanceResult.PASSED,
        ))
        db.add(SiteEntryRecord(
            component_id=comp_b.id,
            contractor_id=party_b.id,
            entered_at=datetime.now(),
            stack_location=f"B区-{RUN_ID}",
            inspector="测试员B",
            acceptance=AcceptanceResult.PASSED,
        ))

        return {
            "project_a_id": proj_a.id,
            "project_b_id": proj_b.id,
            "comp_a_id": comp_a.id,
            "comp_b_id": comp_b.id,
            "trace_a": comp_a.trace_code,
            "trace_b": comp_b.trace_code,
            "party_b_id": party_b.id,
            "user_b": CONTRACTOR_B_USER,
        }


def _cleanup(fix: dict) -> None:
    """清掉本轮插入的隔离测试数据，不污染种子。"""
    with session_scope() as db:
        db.execute(delete(SiteEntryRecord).where(
            SiteEntryRecord.component_id.in_([fix["comp_a_id"], fix["comp_b_id"]])
        ))
        db.execute(delete(Component).where(
            Component.id.in_([fix["comp_a_id"], fix["comp_b_id"]])
        ))
        db.execute(delete(Project).where(Project.id == fix["project_b_id"]))
        db.execute(delete(User).where(User.username == fix["user_b"]))
        db.execute(delete(Party).where(Party.id == fix["party_b_id"]))


# ---------------------------------------------------------------------------
# HTTP 调用
# ---------------------------------------------------------------------------
def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _eligible(token: str) -> list:
    r = requests.get(
        f"{BASE}/api/site/hoisting/eligible",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"== run_id={RUN_ID} 准备隔离数据 ==")
    fix = _setup_isolation_fixture()
    print(f"  project_A.id={fix['project_a_id']}  project_B.id={fix['project_b_id']}")
    print(f"  trace_A={fix['trace_a']}  trace_B={fix['trace_b']}")

    try:
        print(f"== 承包方A 登录 ==")
        token_a = _login(CONTRACTOR_A_USER, CONTRACTOR_A_PASS)
        list_a: list = _eligible(token_a)
        codes_a: Set[str] = {c["trace_code"] for c in list_a}
        print(f"  A 收到 {len(list_a)} 条")

        print(f"== 承包方B 登录 ==")
        token_b = _login(CONTRACTOR_B_USER, CONTRACTOR_B_PASS)
        list_b: list = _eligible(token_b)
        codes_b: Set[str] = {c["trace_code"] for c in list_b}
        print(f"  B 收到 {len(list_b)} 条")

        # ---- 断言 ----
        failures = []

        # 1) A 不应看到 B 的构件（这是本次修复的核心点）
        if fix["trace_b"] in codes_a:
            failures.append(
                f"[FAIL] 承包方A 的可吊装列表里出现了 B 的构件 {fix['trace_b']} —— "
                "项目隔离失败，已复现生产事故"
            )
        else:
            print(f"  [OK] A 看不到 B 的构件 {fix['trace_b']}")

        # 2) B 不应看到 A 的构件
        if fix["trace_a"] in codes_b:
            failures.append(
                f"[FAIL] 承包方B 的可吊装列表里出现了 A 的构件 {fix['trace_a']} —— "
                "项目隔离失败"
            )
        else:
            print(f"  [OK] B 看不到 A 的构件 {fix['trace_a']}")

        # 3) A 至少能看到自己项目的构件（正向用例：自己项目的不漏）
        if fix["trace_a"] not in codes_a:
            failures.append(
                f"[FAIL] 承包方A 看不到本项目构件 {fix['trace_a']} —— 过度隔离"
            )
        else:
            print(f"  [OK] A 能看到本项目构件 {fix['trace_a']}")

        # 4) B 至少能看到自己项目的构件
        if fix["trace_b"] not in codes_b:
            failures.append(
                f"[FAIL] 承包方B 看不到本项目构件 {fix['trace_b']} —— 过度隔离"
            )
        else:
            print(f"  [OK] B 能看到本项目构件 {fix['trace_b']}")

        if failures:
            print("\n".join(failures))
            return 1
        print("\n[OK] 跨项目隔离生效，A/B 各自仅看见本项目构件。")
        return 0
    finally:
        print("== 清理隔离数据 ==")
        _cleanup(fix)


if __name__ == "__main__":
    sys.exit(main())
