"""离线同步接口：工地扫码终端弱网缓存回传。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import OfflineSyncLog, User
from ..schemas import SyncBatchIn, SyncBatchOut
from ..services import apply_offline_event

router = APIRouter(prefix="/api/sync", tags=["离线同步"])


@router.post("/batch", response_model=SyncBatchOut, summary="弱网恢复后批量回传扫码事件")
def sync_batch(
    body: SyncBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    accepted = 0
    rejected = 0
    errors: list[dict] = []
    for item in body.items:
        try:
            result = apply_offline_event(
                db,
                event_type=item.event_type,
                payload=item.payload,
                occurred_at=item.occurred_at,
                requester=user,
            )
            if result == "ok":
                accepted += 1
            else:
                rejected += 1
                errors.append({"event_type": item.event_type, "error": result})
        except Exception as exc:  # noqa: BLE001
            rejected += 1
            errors.append({"event_type": item.event_type, "error": str(exc)})
    db.add(
        OfflineSyncLog(
            client_id=body.client_id,
            batch_id=body.batch_id,
            payload={"items": [i.model_dump(mode="json") for i in body.items]},
            status="accepted" if rejected == 0 else "partial",
        )
    )
    db.commit()
    return SyncBatchOut(batch_id=body.batch_id, accepted=accepted, rejected=rejected, errors=errors)
