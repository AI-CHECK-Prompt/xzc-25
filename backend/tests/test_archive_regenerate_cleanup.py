"""离线回归：generate_archive 再次触发时清理旧 ZIP 文件。

事故复现：
  建设单位在节点连接完成后再次触发档案归档，平台使用相同档案号（带
  时间戳后缀）在存储目录里覆盖写入新 ZIP 文件，但旧 ZIP 文件未被清理。
  长期运行后存储目录堆积大量同名或类似命名的历史档案包，运维人员在
  月度磁盘巡检时才发现存储占用持续增长。

修复期望：
  同一构件再次归档时，DB 记录指向新文件路径的同时，磁盘上的旧 ZIP
  必须被清理（且只在确实存在时被清理，不影响新档案生成）。

本用例无 PostgreSQL / Docker 依赖，用 SQLite 内存库 + 临时存储目录
直接调用 generate_archive()，验证：
  1) 两次归档之间，存储目录只保留最新一份 ZIP；
  2) DB 仍只对应一条 ArchivePackage，file_path 指向新文件；
  3) 旧文件已被人为删除时再次归档不抛异常；
  4) 旧路径不在 storage_dir 下时不会被误删（防御性）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# 切到 SQLite 内存库，避免依赖 PostgreSQL
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 在 import 任何 app.* 之前先准备好 engine
import app.db as appdb  # noqa: E402
import app.services as services  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import (  # noqa: E402
    ArchivePackage,
    Component,
    ComponentType,
    Party,
    PartyRole,
    Project,
    User,
)

# 占位密码哈希：generate_archive 不会校验密码
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


# 把 app.db / services 都指向我们的 SQLite + 临时存储目录
appdb.session_scope = _Scope  # type: ignore[assignment]
appdb.engine = engine  # type: ignore[assignment]

# 准备一个临时存储目录，并把它注入到 services.settings（generate_archive
# 直接通过模块级 settings 引用 storage_dir）
TMP_STORAGE = Path(tempfile.mkdtemp(prefix="xzc25-archive-test-"))
original_storage_dir = services.settings.storage_dir
services.settings.storage_dir = str(TMP_STORAGE)


def _teardown_storage() -> None:
    """测试结束还原 storage_dir 并清理临时目录。"""
    services.settings.storage_dir = original_storage_dir
    if TMP_STORAGE.exists():
        shutil.rmtree(TMP_STORAGE, ignore_errors=True)


def _seed(run_id: str) -> dict:
    """构造一个最小可用的：构件 + 项目 + 业主方 + 业主账号。

    run_id 用于在每次测试间区分 Party.code / Project.code / trace_code，
    避免 SQLite 内存库在多次调用间出现唯一约束冲突。
    """
    with _Scope() as db:
        factory = Party(code=f"FACTORY-{run_id}", name=f"测试工厂-{run_id}",
                        role=PartyRole.FACTORY, contact="", address="")
        owner_party = Party(code=f"OWNER-{run_id}", name=f"测试业主-{run_id}",
                            role=PartyRole.OWNER, contact="", address="")
        db.add_all([factory, owner_party])
        db.flush()

        proj = Project(
            code=f"PRJ-{run_id}", name=f"档案清理测试项目-{run_id}", location="",
            description="",
            owner_party_id=owner_party.id,
            contractor_party_id=owner_party.id,
            supervisor_party_id=owner_party.id,
            start_date=datetime.now(),
        )
        db.add(proj)
        db.flush()

        comp = Component(
            trace_code=f"PC-{run_id}-0001",
            rfid_tag=f"RFID-{run_id}-0001",
            project_id=proj.id,
            factory_id=factory.id,
            component_type=ComponentType.EXTERNAL_WALL,
            spec=run_id,
            quantity=1,
            current_stage="已归档",
        )
        db.add(comp)
        db.flush()

        owner_user = User(
            username=f"owner_{run_id.lower()}",
            password_hash=USER_DUMMY_HASH,
            full_name=f"测试业主-{run_id}",
            role=PartyRole.OWNER,
            party_id=owner_party.id,
        )
        db.add(owner_user)

        return {
            "comp_id": comp.id,
            "trace_code": comp.trace_code,
            "owner_username": f"owner_{run_id.lower()}",
        }


def _get_component_and_owner(fix: dict) -> tuple[Component, User]:
    with _Scope() as db:
        comp = db.get(Component, fix["comp_id"])
        owner = db.query(User).filter(User.username == fix["owner_username"]).first()
        return comp, owner


# ---------------------------------------------------------------------------
# 测试 1：再次归档时旧文件必须被清理
# ---------------------------------------------------------------------------
def test_regenerate_cleans_old_zip() -> bool:
    print("== 测试 1：再次归档时旧 ZIP 必须被清理 ==")
    fix = _seed("CLEAN")
    comp, owner = _get_component_and_owner(fix)

    with _Scope() as db:
        comp2 = db.get(Component, fix["comp_id"])
        owner2 = db.query(User).filter(User.username == fix["owner_username"]).first()
        first = services.generate_archive(db, comp2, owner2)
        first_path = first.file_path

    # 时间戳精度为秒；为确保第二次 archive_no 真的不同，sleep 一下
    time.sleep(1.1)
    with _Scope() as db:
        comp3 = db.get(Component, fix["comp_id"])
        owner3 = db.query(User).filter(User.username == fix["owner_username"]).first()
        second = services.generate_archive(db, comp3, owner3)
        second_path = second.file_path

    failures = []
    if first_path == second_path:
        failures.append(f"两次归档路径相同（{first_path}），时间戳未生效")
    if os.path.exists(first_path):
        failures.append(f"[FAIL] 旧文件未被清理：{first_path}")
    else:
        print(f"  [OK] 旧文件已清理：{first_path}")
    if not os.path.isfile(second_path):
        failures.append(f"[FAIL] 新文件未生成：{second_path}")
    else:
        print(f"  [OK] 新文件存在：{second_path}")

    # DB 仍只对应一条记录，且 file_path 指向新文件
    with _Scope() as db:
        rows = db.query(ArchivePackage).filter(ArchivePackage.component_id == fix["comp_id"]).all()
    if len(rows) != 1:
        failures.append(f"[FAIL] ArchivePackage 行数={len(rows)}，期望 1")
    elif rows[0].file_path != second_path:
        failures.append(f"[FAIL] DB.file_path={rows[0].file_path}，期望 {second_path}")
    else:
        print(f"  [OK] DB 仅保留 1 条记录，file_path 指向新文件")

    # 存储目录里也不应残留其它带相同 trace_code 后缀的旧 ZIP
    leftover = [p for p in TMP_STORAGE.iterdir()
                if p.is_file() and p.suffix == ".zip" and p != Path(second_path)]
    if leftover:
        failures.append(f"[FAIL] 存储目录里残留旧 ZIP：{leftover}")
    else:
        print(f"  [OK] 存储目录中无残留历史档案包")

    if failures:
        for f in failures:
            print(f)
        return False
    print("  [PASS] 测试 1 通过\n")
    return True


# ---------------------------------------------------------------------------
# 测试 2：旧文件已经被人为删除，再次归档不抛异常
# ---------------------------------------------------------------------------
def test_regenerate_when_old_file_missing() -> bool:
    print("== 测试 2：旧文件已缺失时再次归档 ==")
    fix = _seed("MISSING")
    comp, owner = _get_component_and_owner(fix)

    with _Scope() as db:
        comp2 = db.get(Component, fix["comp_id"])
        owner2 = db.query(User).filter(User.username == fix["owner_username"]).first()
        first = services.generate_archive(db, comp2, owner2)
        first_path = first.file_path

    # 模拟运维 / 磁盘巡检已经手工清理过旧文件
    if os.path.isfile(first_path):
        os.remove(first_path)

    try:
        time.sleep(1.1)
        with _Scope() as db:
            comp3 = db.get(Component, fix["comp_id"])
            owner3 = db.query(User).filter(User.username == fix["owner_username"]).first()
            second = services.generate_archive(db, comp3, owner3)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 旧文件缺失时再次归档抛异常：{exc!r}")
        return False

    if not os.path.isfile(second.file_path):
        print(f"  [FAIL] 新文件未生成：{second.file_path}")
        return False
    if os.path.exists(first_path):
        print(f"  [FAIL] 旧路径上又出现了文件：{first_path}")
        return False
    print(f"  [OK] 旧文件缺失场景下正常生成新档案：{second.file_path}")
    print("  [PASS] 测试 2 通过\n")
    return True


# ---------------------------------------------------------------------------
# 测试 3：旧路径不在 storage_dir 下时不应被误删（防御性）
# ---------------------------------------------------------------------------
def test_regenerate_never_deletes_outside_storage() -> bool:
    print("== 测试 3：旧路径不在 storage_dir 时不被误删 ==")

    # 准备一个 storage_dir 之外的「假历史档案」
    outside_dir = Path(tempfile.mkdtemp(prefix="xzc25-outside-"))
    fake_old = outside_dir / "ARCH-FAKE-00000000-ABCDEF.zip"
    fake_old.write_bytes(b"do-not-touch")
    try:
        try:
            services._cleanup_obsolete_archive_file(str(fake_old), str(TMP_STORAGE / "new.zip"))
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] 防御性删除路径时抛异常：{exc!r}")
            return False
        if not fake_old.exists():
            print(f"  [FAIL] 误删了 storage_dir 之外的文件：{fake_old}")
            return False
        print(f"  [OK] 防御性检查生效，未误删 {fake_old}")
        print("  [PASS] 测试 3 通过\n")
        return True
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)


def main() -> int:
    results = [
        test_regenerate_cleans_old_zip(),
        test_regenerate_when_old_file_missing(),
        test_regenerate_never_deletes_outside_storage(),
    ]
    try:
        if all(results):
            print("[OK] 全部 3 个回归用例通过：再次归档时旧 ZIP 已被清理，"
                  "DB 记录保持唯一，防御性检查生效。")
            return 0
        print("[FAIL] 有回归用例未通过，详见上方输出。")
        return 1
    finally:
        _teardown_storage()


if __name__ == "__main__":
    sys.exit(main())
