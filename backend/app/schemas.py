"""Pydantic 模式：API 进出参约束。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AcceptanceResult,
    ArchiveStatus,
    ComponentType,
    ConnectionType,
    HoistResult,
    PartyRole,
    TransportStatus,
)


# ---------- 通用 ----------
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: PartyRole
    party_id: int


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    role: PartyRole
    contact: str
    address: str


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    location: str
    description: str


# ---------- 构件生产 ----------
class ComponentCreate(BaseModel):
    project_id: int
    component_type: ComponentType
    spec: str = ""
    quantity: int = 1
    mould_no: str
    rebar_batch: str
    concrete_ratio: str
    pour_at: datetime
    curing_record: str = ""
    strength_report: str = ""
    embedded_parts: Dict[str, Any] = Field(default_factory=dict)
    factory_inspection: AcceptanceResult = AcceptanceResult.PASSED


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trace_code: str
    rfid_tag: str
    project_id: int
    factory_id: int
    component_type: ComponentType
    spec: str
    mould_no: str
    rebar_batch: str
    concrete_ratio: str
    pour_at: Optional[datetime]
    curing_record: str
    strength_report: str
    embedded_parts: Dict[str, Any]
    factory_inspection: AcceptanceResult
    current_stage: str
    qr_payload: str


class ComponentBatchItem(BaseModel):
    """批量录入单条：同批次所有条目必须归属同一 project_id（顶层字段）。"""
    component_type: ComponentType
    spec: str = ""
    quantity: int = 1
    mould_no: str
    rebar_batch: str
    concrete_ratio: str
    pour_at: datetime
    curing_record: str = ""
    strength_report: str = ""
    embedded_parts: Dict[str, Any] = Field(default_factory=dict)
    factory_inspection: AcceptanceResult = AcceptanceResult.PASSED


class ComponentBatchCreate(BaseModel):
    """工厂平板端批量录入请求。

    client_id + batch_id 共同构成幂等键：同一批数据重发将直接复用历史结果，
    避免因弱网重试导致追溯码被重复占用。
    """
    client_id: str = Field(..., min_length=1, max_length=64)
    batch_id: str = Field(..., min_length=1, max_length=64)
    project_id: int
    items: List[ComponentBatchItem] = Field(..., min_length=1, max_length=500)


class ComponentBatchItemResult(BaseModel):
    index: int
    component_id: int
    trace_code: str
    rfid_tag: str
    qr_payload: str


class ComponentBatchResult(BaseModel):
    batch_id: str
    accepted: int
    rejected: int
    items: List[ComponentBatchItemResult] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    idempotent_replay: bool = False  # True = 命中幂等表直接返回历史结果


# ---------- 出厂 ----------
class FactoryOutCreate(BaseModel):
    component_id: int
    transport_party_id: int
    out_at: datetime
    vehicle_no: str
    driver: str
    driver_phone: str = ""
    route_plan: str
    inspection_conclusion: AcceptanceResult = AcceptanceResult.PASSED


class FactoryOutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    transport_party_id: int
    out_at: datetime
    vehicle_no: str
    driver: str
    route_plan: str
    inspection_conclusion: AcceptanceResult


# ---------- 运输 ----------
class TelemetryIn(BaseModel):
    component_id: int
    transport_record_id: int
    reported_at: datetime
    longitude: float
    latitude: float
    temperature: float
    humidity: float
    status: TransportStatus = TransportStatus.IN_TRANSIT


class TelemetryBatchIn(BaseModel):
    batch_id: str
    items: List[TelemetryIn]


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    alert_type: str
    detail: str
    resolved: bool
    created_at: datetime


# ---------- 进场 ----------
class SiteEntryCreate(BaseModel):
    component_id: int
    entered_at: datetime
    stack_location: str
    inspector: str
    acceptance: AcceptanceResult
    remark: str = ""
    photo_urls: List[str] = Field(default_factory=list)


class SiteEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    entered_at: datetime
    stack_location: str
    inspector: str
    acceptance: AcceptanceResult
    remark: str


# ---------- 吊装 ----------
class HoistingCreate(BaseModel):
    component_id: int
    hoisted_at: datetime
    equipment_no: str
    signal_worker: str
    rigger: str
    coord_lng: float
    coord_lat: float
    result: HoistResult


class HoistingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    hoisted_at: datetime
    equipment_no: str
    signal_worker: str
    rigger: str
    result: HoistResult


# ---------- 节点连接 ----------
class JointCreate(BaseModel):
    component_id: int
    grout_at: datetime
    grout_batch: str
    bedding_at: Optional[datetime] = None
    connection_type: ConnectionType
    operator: str
    photo_urls: List[str] = Field(default_factory=list)


class JointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    grout_at: datetime
    grout_batch: str
    connection_type: ConnectionType
    operator: str


# ---------- 隐蔽验收 ----------
class ConcealedCreate(BaseModel):
    component_id: int
    accepted_at: datetime
    quality_grade: str
    inspector: str
    photo_urls: List[str] = Field(default_factory=list)
    video_url: str = ""
    conclusion: str = ""


class ConcealedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    accepted_at: datetime
    quality_grade: str
    inspector: str
    conclusion: str


# ---------- 成品保护 ----------
class ProtectionCreate(BaseModel):
    component_id: int
    decoration: str = ""
    mep: str = ""
    measures: str = ""
    risk_warning: str = ""


class ProtectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    decoration: str
    mep: str
    measures: str
    risk_warning: str
    updated_at: datetime


# ---------- 档案 ----------
class ArchiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int
    archive_no: str
    file_path: str
    status: ArchiveStatus
    submitted_at: Optional[datetime]
    accepted_at: Optional[datetime]
    created_at: datetime


# ---------- 离线同步 ----------
class SyncItem(BaseModel):
    event_type: str  # site_entry / hoisting / joint / concealed / protection / telemetry
    payload: Dict[str, Any]
    occurred_at: datetime
    client_id: str


class SyncBatchIn(BaseModel):
    client_id: str
    batch_id: str
    items: List[SyncItem]


class SyncBatchOut(BaseModel):
    batch_id: str
    accepted: int
    rejected: int
    errors: List[Dict[str, str]] = Field(default_factory=list)


# ---------- 追溯聚合 ----------
class TraceTimelineItem(BaseModel):
    stage: str
    occurred_at: Optional[datetime]
    actor: str
    party_role: PartyRole
    summary: str
    extras: Dict[str, Any] = Field(default_factory=dict)


class TraceResponse(BaseModel):
    component: ComponentOut
    timeline: List[TraceTimelineItem]
    archives: List[ArchiveOut]


TokenOut.model_rebuild()
