"""多班组平板端并发抢号压测 —— 回归用例。

场景还原：
  4 个班组（线程）同时调用 /api/components/batch，各自一次性提交 50 件，
  共 200 件。修复前由于 count()+1 存在 TOCTOU，会出现「追溯码已存在」；
  修复后期望全部 200 件入库，追溯码连续无重复。

使用方法：
  1) 启动后端：cd backend && uvicorn app.main:app --port 8000
  2) cd backend && python tests/test_concurrent_trace_code.py
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import time
import uuid
from datetime import datetime
from typing import List

import requests

BASE = "http://localhost:8000"
USERNAME = "factory01"
PASSWORD = "123456"
PROJECT_ID = 1
WORKERS = 4
BATCH_SIZE = 50  # 每班组 50 件 → 总 200 件


def login() -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def submit_one_batch(token: str, worker_id: int) -> dict:
    """单个班组一次性提交 BATCH_SIZE 件。"""
    headers = {"Authorization": f"Bearer {token}"}
    client_id = f"tablet-team-{worker_id:02d}"
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat()
    items = [
        {
            "component_type": "外墙板",
            "spec": f"YQB-200-{worker_id:02d}-{i:03d}",
            "quantity": 1,
            "mould_no": f"M-{worker_id:02d}-{i:03d}",
            "rebar_batch": f"R-{now[:10]}-{worker_id:02d}",
            "concrete_ratio": "C40",
            "pour_at": now,
            "curing_record": "标准养护 7d",
            "strength_report": f"STR-{worker_id:02d}-{i:03d}",
            "embedded_parts": {"lift": 4},
            "factory_inspection": "合格",
        }
        for i in range(BATCH_SIZE)
    ]
    body = {
        "client_id": client_id,
        "batch_id": batch_id,
        "project_id": PROJECT_ID,
        "items": items,
    }
    t0 = time.perf_counter()
    r = requests.post(
        f"{BASE}/api/components/batch",
        json=body,
        headers=headers,
        timeout=60,
    )
    dt = time.perf_counter() - t0
    return {
        "worker": worker_id,
        "status": r.status_code,
        "elapsed_s": round(dt, 2),
        "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text,
    }


def main() -> int:
    print("== 登录并取 token ==")
    token = login()
    print(f"token 取得: {token[:24]}...")

    print(f"== {WORKERS} 班组 × {BATCH_SIZE} 件 并发提交 ==")
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(submit_one_batch, token, i) for i in range(1, WORKERS + 1)]
        results = [f.result() for f in cf.as_completed(futures)]
    total = time.perf_counter() - t0
    print(f"== 总耗时 {total:.2f}s ==")

    # 汇总
    all_codes: List[str] = []
    total_accepted = 0
    fail_workers = []
    for r in results:
        b = r["body"]
        if r["status"] == 200 and isinstance(b, dict):
            codes = [it["trace_code"] for it in b.get("items", [])]
            all_codes.extend(codes)
            total_accepted += b.get("accepted", 0)
            print(
                f"  worker={r['worker']:>2}  status=200  "
                f"accepted={b.get('accepted'):>3}  range=[{codes[0]} .. {codes[-1]}]  "
                f"elapsed={r['elapsed_s']}s"
            )
        else:
            fail_workers.append(r)
            print(f"  worker={r['worker']:>2}  status={r['status']}  body={b}")

    expected = WORKERS * BATCH_SIZE
    print(f"\n== 汇总 ==")
    print(f"  期望：{expected} 件，实际 accepted：{total_accepted}")
    print(f"  班组失败：{len(fail_workers)}")
    print(f"  追溯码总数：{len(all_codes)}")
    print(f"  唯一追溯码数：{len(set(all_codes))}")
    duplicate = len(all_codes) - len(set(all_codes))
    print(f"  重复追溯码：{duplicate}")

    if total_accepted == expected and duplicate == 0 and not fail_workers:
        print("\n[OK] 全部 200 件入库，追溯码连续无重复，无任何冲突。")
        return 0
    print("\n[FAIL] 并发场景下存在冲突，详见上方输出。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
