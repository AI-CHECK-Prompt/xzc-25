"""数据库种子：六方参与方、默认账号、示例项目。

幂等：已存在则跳过。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy.orm import Session

from .auth import hash_password
from .db import Base, engine, session_scope
from .models import (
    AcceptanceResult,
    Component,
    ComponentType,
    ConcealedAcceptance,
    FactoryOutRecord,
    HoistingRecord,
    JointConnection,
    Party,
    PartyRole,
    Project,
    ProjectMilestone,
    ProtectionRecord,
    SiteEntryRecord,
    User,
)


def _ensure_tables() -> None:
    """确保表已存在（首次启动时）。"""
    Base.metadata.create_all(bind=engine)


def _ensure_idempotent_unique_constraints() -> None:
    """create_all 不会改既有表；对老库补齐离线同步幂等约束。

    若约束已存在则跳过；执行失败时仅打印告警，不阻断启动。
    """
    statements = [
        "ALTER TABLE offline_sync_logs "
        "ADD CONSTRAINT uq_offline_sync_client_batch UNIQUE (client_id, batch_id)",
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.exec_driver_sql(sql)
            except Exception as exc:  # noqa: BLE001
                # 已存在 / 旧版本 PG 语法差异等情况，不影响新库
                print(f"[bootstrap] 跳过约束补齐：{sql} -> {exc}")


def _ensure_parties(db: Session) -> Dict[PartyRole, Party]:
    """确保六方参与方存在。"""
    presets = [
        ("FACTORY01", "中建构件华东工厂", PartyRole.FACTORY, "吴经理 13800000001", "江苏省南京市江宁区临江大道1号"),
        ("TRANSPORT01", "鸿运物流有限公司", PartyRole.TRANSPORT, "陈调度 13800000002", "江苏省南京市浦口区物流大道18号"),
        ("CONTRACTOR01", "中铁建工总承包部", PartyRole.CONTRACTOR, "王项目经理 13800000003", "浙江省杭州市余杭区工地临时办公区"),
        ("SUPERVISOR01", "华信工程监理公司", PartyRole.SUPERVISOR, "刘总监 13800000004", "浙江省杭州市余杭区监理办公室"),
        ("OWNER01", "阳光城开发集团", PartyRole.OWNER, "赵主管 13800000005", "浙江省杭州市西湖区文三路阳光城总部"),
        ("QUALITY01", "杭州市建设工程质量监督总站", PartyRole.QUALITY, "周监督员 13800000006", "浙江省杭州市上城区监督总站"),
    ]
    result: Dict[PartyRole, Party] = {}
    for code, name, role, contact, address in presets:
        p = db.query(Party).filter(Party.code == code).first()
        if not p:
            p = Party(code=code, name=name, role=role, contact=contact, address=address)
            db.add(p)
            db.flush()
        result[role] = p
    return result


def _ensure_users(db: Session, parties: Dict[PartyRole, Party]) -> None:
    """默认账号，密码统一 123456。"""
    presets = [
        ("factory01", "吴经理", PartyRole.FACTORY),
        ("transport01", "陈调度", PartyRole.TRANSPORT),
        ("contractor01", "王项目经理", PartyRole.CONTRACTOR),
        ("supervisor01", "刘总监", PartyRole.SUPERVISOR),
        ("owner01", "赵主管", PartyRole.OWNER),
        ("quality01", "周监督员", PartyRole.QUALITY),
        ("quality02", "李监督员", PartyRole.QUALITY),  # 第二抽检员，演练轮岗复核
    ]
    for username, full_name, role in presets:
        u = db.query(User).filter(User.username == username).first()
        if not u:
            u = User(
                username=username,
                password_hash=hash_password("123456"),
                full_name=full_name,
                role=role,
                party_id=parties[role].id,
            )
            db.add(u)


def _ensure_projects(db: Session, parties: Dict[PartyRole, Party]) -> List[Project]:
    projects_data = [
        {
            "code": "PRJ-SUN-001",
            "name": "阳光城A区一标段",
            "location": "浙江省杭州市余杭区文一西路",
            "description": "12 栋高层装配式住宅，PC 率 35%",
        },
        {
            "code": "PRJ-SUN-002",
            "name": "阳光城B区二标段",
            "location": "浙江省杭州市余杭区文一西路",
            "description": "8 栋高层装配式住宅，PC 率 30%",
        },
    ]
    result = []
    for data in projects_data:
        p = db.query(Project).filter(Project.code == data["code"]).first()
        if not p:
            p = Project(
                code=data["code"],
                name=data["name"],
                location=data["location"],
                description=data["description"],
                owner_party_id=parties[PartyRole.OWNER].id,
                contractor_party_id=parties[PartyRole.CONTRACTOR].id,
                supervisor_party_id=parties[PartyRole.SUPERVISOR].id,
                start_date=datetime(2025, 6, 1),
            )
            db.add(p)
            db.flush()
        result.append(p)
    return result


def ensure_seed() -> None:
    _ensure_tables()
    _ensure_idempotent_unique_constraints()
    with session_scope() as db:
        parties = _ensure_parties(db)
        _ensure_users(db, parties)
        projects = _ensure_projects(db, parties)
        _ensure_default_milestones(db, projects)
        db.commit()


def _ensure_default_milestones(db: Session, projects: List[Project]) -> None:
    """每个项目内置 5 个关键节点，构成甘特图骨架。"""
    stages = [
        ("P1", "生产完成", "成品保护", 0),
        ("P2", "运输完成", "已卸货", 1),
        ("P3", "进场完成", "已进场", 2),
        ("P4", "吊装完成", "已吊装", 3),
        ("P5", "档案归档", "已归档", 4),
    ]
    for p in projects:
        for code, name, stage, sort_no in stages:
            exists = (
                db.query(ProjectMilestone)
                .filter(ProjectMilestone.project_id == p.id, ProjectMilestone.code == code)
                .first()
            )
            if not exists:
                db.add(ProjectMilestone(
                    project_id=p.id,
                    code=code,
                    name=name,
                    stage=stage,
                    weight=1.0,
                    sort_no=sort_no,
                ))
