"""SQLAlchemy ORM 模型：装配式建筑构件全过程质量追溯。

参与方权责：
  工厂 → 生产质量与出厂检验
  运输 → 运输过程完好与路线合规
  施工 → 进场、吊装、节点、成品保护
  监理 → 隐蔽验收与质量评定
  建设 → 多方协调与档案
  质监 → 监督抽检与行政处罚
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class PartyRole(str, enum.Enum):
    FACTORY = "factory"          # 预制构件工厂
    TRANSPORT = "transport"      # 运输单位
    CONTRACTOR = "contractor"    # 施工总承包
    SUPERVISOR = "supervisor"    # 监理单位
    OWNER = "owner"              # 建设单位
    QUALITY = "quality"          # 质量监督机构


class ComponentType(str, enum.Enum):
    EXTERNAL_WALL = "外墙板"
    INTERNAL_WALL = "内墙板"
    STAIRS = "楼梯"
    FLOOR_SLAB = "叠合楼板"
    BEAM = "预制梁"
    COLUMN = "预制柱"
    BALCONY = "预制阳台"
    BATHROOM = "整体卫浴"


class AcceptanceResult(str, enum.Enum):
    PASSED = "合格"
    UNPASSED = "不合格"
    PENDING = "待定"


class TransportStatus(str, enum.Enum):
    LOADED = "已装车"
    IN_TRANSIT = "运输中"
    ARRIVED = "已到达"
    UNLOADED = "已卸货"
    OFF_ROUTE = "偏离路线"
    OVERSTAY = "超时停留"
    TEMP_OUT = "温湿度越界"


class HoistResult(str, enum.Enum):
    SUCCESS = "一次就位"
    ADJUSTED = "调整后到位"
    FAILED = "未到位"


class ConnectionType(str, enum.Enum):
    GROUT_SLEEVE = "灌浆套筒"
    GROUT_BEARING = "灌浆座浆"
    POST_CAST = "后浇连接"
    WELD = "焊接连接"
    BOLT = "螺栓连接"


class ArchiveStatus(str, enum.Enum):
    DRAFT = "草稿"
    GENERATED = "已生成"
    SUBMITTED = "已报送"
    ACCEPTED = "已签收"
    REJECTED = "退回整改"


# ---------------------------------------------------------------------------
# 基础表
# ---------------------------------------------------------------------------
class Party(Base):
    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[PartyRole] = mapped_column(Enum(PartyRole), index=True)
    contact: Mapped[str] = mapped_column(String(64), default="")
    address: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    full_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[PartyRole] = mapped_column(Enum(PartyRole), index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    location: Mapped[str] = mapped_column(String(256), default="")
    owner_party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"))
    contractor_party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"))
    supervisor_party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"))
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 构件全生命周期
# ---------------------------------------------------------------------------
class Component(Base):
    """构件主表，唯一追溯码。"""
    __tablename__ = "components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 唯一追溯码
    rfid_tag: Mapped[str] = mapped_column(String(64), default="", index=True)     # 射频标签
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    component_type: Mapped[ComponentType] = mapped_column(Enum(ComponentType), index=True)
    spec: Mapped[str] = mapped_column(String(128), default="")  # 规格型号
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # 生产信息
    mould_no: Mapped[str] = mapped_column(String(64), default="")           # 模具编号
    rebar_batch: Mapped[str] = mapped_column(String(64), default="")        # 钢筋原材料批号
    concrete_ratio: Mapped[str] = mapped_column(String(64), default="")     # 混凝土配合比
    pour_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)   # 浇筑时间
    curing_record: Mapped[str] = mapped_column(Text, default="")            # 养护记录
    strength_report: Mapped[str] = mapped_column(String(128), default="")  # 强度报告编号
    embedded_parts: Mapped[dict] = mapped_column(JSON, default=dict)        # 预埋件信息
    factory_inspection: Mapped[AcceptanceResult] = mapped_column(
        Enum(AcceptanceResult), default=AcceptanceResult.PASSED
    )

    # 业务状态
    current_stage: Mapped[str] = mapped_column(String(32), default="已生产")
    qr_payload: Mapped[str] = mapped_column(Text, default="")               # 二维码内容

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FactoryOutRecord(Base):
    """构件出厂记录。"""
    __tablename__ = "factory_out_records"
    __table_args__ = (UniqueConstraint("component_id", name="uq_factory_out_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)
    transport_party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    out_at: Mapped[datetime] = mapped_column(DateTime)
    vehicle_no: Mapped[str] = mapped_column(String(32))
    driver: Mapped[str] = mapped_column(String(32))
    driver_phone: Mapped[str] = mapped_column(String(32), default="")
    route_plan: Mapped[str] = mapped_column(Text, default="")
    certificate_pdf: Mapped[str] = mapped_column(String(256), default="")  # 出厂合格证
    inspection_conclusion: Mapped[AcceptanceResult] = mapped_column(Enum(AcceptanceResult))


class TransportTelemetry(Base):
    """运输环节回传：位置 + 温湿度。"""
    __tablename__ = "transport_telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    transport_record_id: Mapped[int] = mapped_column(ForeignKey("factory_out_records.id"), index=True)

    reported_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    longitude: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    temperature: Mapped[float] = mapped_column(Float)   # 摄氏度
    humidity: Mapped[float] = mapped_column(Float)      # %RH
    status: Mapped[TransportStatus] = mapped_column(Enum(TransportStatus), default=TransportStatus.IN_TRANSIT)


class TransportAlert(Base):
    """运输异常告警。"""
    __tablename__ = "transport_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    telemetry_id: Mapped[int] = mapped_column(ForeignKey("transport_telemetry.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(32))   # OFF_ROUTE / OVERSTAY / TEMP_OUT
    detail: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SiteEntryRecord(Base):
    """构件进场登记。"""
    __tablename__ = "site_entry_records"
    __table_args__ = (UniqueConstraint("component_id", name="uq_site_entry_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    contractor_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    entered_at: Mapped[datetime] = mapped_column(DateTime)
    stack_location: Mapped[str] = mapped_column(String(128))  # 堆放位置
    inspector: Mapped[str] = mapped_column(String(64))
    acceptance: Mapped[AcceptanceResult] = mapped_column(Enum(AcceptanceResult))
    remark: Mapped[str] = mapped_column(Text, default="")
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)


class HoistingRecord(Base):
    """吊装记录。"""
    __tablename__ = "hoisting_records"
    __table_args__ = (UniqueConstraint("component_id", name="uq_hoist_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    contractor_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    hoisted_at: Mapped[datetime] = mapped_column(DateTime)
    equipment_no: Mapped[str] = mapped_column(String(64))   # 吊装设备编号
    signal_worker: Mapped[str] = mapped_column(String(32))  # 信号工
    rigger: Mapped[str] = mapped_column(String(32))         # 司索工
    coord_lng: Mapped[float] = mapped_column(Float)
    coord_lat: Mapped[float] = mapped_column(Float)
    result: Mapped[HoistResult] = mapped_column(Enum(HoistResult))


class JointConnection(Base):
    """节点连接（灌浆、座浆等）。"""
    __tablename__ = "joint_connections"
    __table_args__ = (UniqueConstraint("component_id", name="uq_joint_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    contractor_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    grout_at: Mapped[datetime] = mapped_column(DateTime)
    grout_batch: Mapped[str] = mapped_column(String(64))          # 灌浆料批号
    bedding_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 座浆时间
    connection_type: Mapped[ConnectionType] = mapped_column(Enum(ConnectionType))
    operator: Mapped[str] = mapped_column(String(32))
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)


class ConcealedAcceptance(Base):
    """隐蔽工程验收。"""
    __tablename__ = "concealed_acceptances"
    __table_args__ = (UniqueConstraint("component_id", name="uq_concealed_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    accepted_at: Mapped[datetime] = mapped_column(DateTime)
    quality_grade: Mapped[str] = mapped_column(String(16))   # 合格/优良
    inspector: Mapped[str] = mapped_column(String(32))
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)
    video_url: Mapped[str] = mapped_column(String(256), default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")


class ProtectionRecord(Base):
    """成品保护。"""
    __tablename__ = "protection_records"
    __table_args__ = (UniqueConstraint("component_id", name="uq_protection_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    contractor_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    decoration: Mapped[str] = mapped_column(String(128), default="")
    mep: Mapped[str] = mapped_column(String(128), default="")
    measures: Mapped[str] = mapped_column(Text, default="")
    risk_warning: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TraceSequence(Base):
    """工厂 × 当日 追溯码原子序列。

    多班组并发抢号根因是原先「count()+1」的 SELECT-then-INSERT 存在 TOCTOU。
    此表在 (factory_id, seq_date) 上唯一，行级锁 (SELECT ... FOR UPDATE) 串行化
    同一工厂同一日内的号段分配；不同工厂 / 不同日 完全并行。
    """
    __tablename__ = "trace_sequences"
    __table_args__ = (
        UniqueConstraint("factory_id", "seq_date", name="uq_trace_seq_factory_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    factory_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)
    seq_date: Mapped[datetime] = mapped_column(DateTime, index=True)  # 当日 00:00:00
    next_value: Mapped[int] = mapped_column(Integer, default=1)       # 下一可用序号
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ArchivePackage(Base):
    """电子档案包。"""
    __tablename__ = "archive_packages"
    __table_args__ = (UniqueConstraint("component_id", name="uq_archive_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), index=True)

    archive_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_path: Mapped[str] = mapped_column(String(256))         # ZIP 文件路径
    payload: Mapped[dict] = mapped_column(JSON, default=dict)   # 档案内容
    status: Mapped[ArchiveStatus] = mapped_column(Enum(ArchiveStatus), default=ArchiveStatus.DRAFT)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 离线同步
# ---------------------------------------------------------------------------
class OfflineSyncLog(Base):
    """离线同步日志，用于排查弱网环境缓存是否成功回传。

    (client_id, batch_id) 唯一约束支撑接口幂等：客户端重发同一批
    数据时直接复用历史结果，不再重复插入。
    """
    __tablename__ = "offline_sync_logs"
    __table_args__ = (
        UniqueConstraint("client_id", "batch_id", name="uq_offline_sync_client_batch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="accepted")  # accepted/rejected
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
