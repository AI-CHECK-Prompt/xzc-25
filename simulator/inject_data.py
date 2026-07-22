"""数据注入模拟器：批量灌入一个完整工地项目的全流程数据。

执行：
  docker compose up -d backend
  docker compose exec backend python -m app.self_check   # 自检生成 1 个合格件 + 1 个不合格件
  docker compose up simulator                            # 模拟器额外灌入 28 件

或本地：
  python simulator/inject_data.py --project 阳光城A区一标段
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List

import httpx


API_BASE_DEFAULT = "http://backend:8000"

ACCOUNTS = {
    "factory01": "123456",
    "transport01": "123456",
    "contractor01": "123456",
    "supervisor01": "123456",
    "owner01": "123456",
}

COMPONENT_TYPES = ["外墙板", "内墙板", "叠合楼板", "楼梯", "预制梁", "预制阳台", "整体卫浴"]

ROUTE_PLAN_TEMPLATE = "南京工厂 → 沪宁高速 → 杭州北出口 → 工地临时堆场"

TELEMETRY_BASE = {"lng": 118.78, "lat": 32.04}  # 南京工厂起点

EQUIPMENT_POOL = [f"TC70{random.randint(0, 9)}{random.randint(0, 9)}" for _ in range(5)]


def _login(client: httpx.Client, username: str, password: str) -> str:
    resp = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _wait_backend(client: httpx.Client, retries: int = 60) -> None:
    for i in range(retries):
        try:
            r = client.get("/", timeout=2.0)
            if r.status_code == 200:
                print(f"[模拟器] 后端就绪: {r.json()}")
                return
        except Exception:
            pass
        time.sleep(2.0)
    raise RuntimeError("后端服务在 120 秒内未就绪")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="阳光城A区一标段", help="目标项目名称")
    parser.add_argument("--api-base", default=API_BASE_DEFAULT, help="后端 API 地址")
    parser.add_argument("--count", type=int, default=28, help="额外灌入构件数量")
    parser.add_argument("--unpassed-ratio", type=float, default=0.07, help="不合格比例")
    args = parser.parse_args()

    base = args.api_base.rstrip("/")
    client = httpx.Client(base_url=base, timeout=20.0)

    _wait_backend(client)

    # 1. 登录各参与方
    tokens: Dict[str, str] = {}
    for username, pwd in ACCOUNTS.items():
        tokens[username] = _login(client, username, pwd)
        print(f"[模拟器] 登录成功：{username}")

    # 2. 获取项目与参与方 ID
    projects = client.get("/api/meta/projects", headers=_headers(tokens["owner01"])).json()
    project = next((p for p in projects if p["name"] == args.project), None)
    if not project:
        print(f"[模拟器] 未找到项目 {args.project}，可选项：{[p['name'] for p in projects]}")
        return 1
    project_id = project["id"]
    print(f"[模拟器] 目标项目：{project['name']} (id={project_id})")

    parties = client.get("/api/meta/parties", headers=_headers(tokens["owner01"])).json()
    factory = next(p for p in parties if p["role"] == "factory")
    transport = next(p for p in parties if p["role"] == "transport")
    contractor = next(p for p in parties if p["role"] == "contractor")
    print(f"[模拟器] 工厂={factory['name']} 运输={transport['name']} 施工={contractor['name']}")

    # 3. 工厂批量录入构件
    now = datetime.now()
    components: List[Dict] = []
    for i in range(args.count):
        comp_type = random.choice(COMPONENT_TYPES)
        payload = {
            "project_id": project_id,
            "component_type": comp_type,
            "spec": f"{comp_type}-3.0m×6.0m-SIM{i:03d}",
            "quantity": 1,
            "mould_no": f"M-SIM{i:03d}",
            "rebar_batch": f"RB-2025-SIM{i:03d}",
            "concrete_ratio": "C40",
            "pour_at": (now - timedelta(days=random.randint(15, 30))).isoformat(),
            "curing_record": f"标准养护 14 天，温度 20±2℃、湿度 ≥95%RH",
            "strength_report": f"STR-2025-SIM{i:03d}",
            "embedded_parts": {"吊点": 4, "电气盒": 2, "灌浆套筒": 6},
            "factory_inspection": "合格",
        }
        r = client.post("/api/components", json=payload, headers=_headers(tokens["factory01"]))
        r.raise_for_status()
        comp = r.json()
        components.append(comp)
        print(f"[模拟器] 录入构件 {i+1}/{args.count}：{comp['trace_code']}")

    # 4. 工厂登记出厂
    factory_out_records: Dict[int, int] = {}
    for c in components:
        out_payload = {
            "component_id": c["id"],
            "transport_party_id": transport["id"],
            "out_at": (now - timedelta(days=random.randint(8, 14))).isoformat(),
            "vehicle_no": f"苏A·{random.randint(10000, 99999)}",
            "driver": random.choice(["张师傅", "李师傅", "王师傅", "陈师傅", "刘师傅"]),
            "driver_phone": f"139{random.randint(10000000, 99999999)}",
            "route_plan": ROUTE_PLAN_TEMPLATE,
            "inspection_conclusion": "合格",
        }
        r = client.post("/api/components/factory-out", json=out_payload, headers=_headers(tokens["factory01"]))
        r.raise_for_status()
        factory_out_records[c["id"]] = r.json()["id"]

    # 5. 运输单位上传 5 段轨迹 + 故意制造 1~2 个告警
    for c in components:
        comp_id = c["id"]
        rec_id = factory_out_records[comp_id]
        out_at = datetime.fromisoformat(c.get("created_at") or now.isoformat()) - timedelta(days=10)
        lng, lat = TELEMETRY_BASE["lng"], TELEMETRY_BASE["lat"]
        for step in range(5):
            lng += random.uniform(0.2, 0.4)
            lat += random.uniform(-0.05, 0.05)
            temp = random.uniform(15, 35)
            hum = random.uniform(40, 80)
            # 故意在第 3 步制造一次温湿度越界
            if step == 2 and random.random() < 0.6:
                temp = random.uniform(61, 70)
                hum = random.uniform(96, 99)
            t_payload = {
                "component_id": comp_id,
                "transport_record_id": rec_id,
                "reported_at": (out_at + timedelta(hours=step * 2)).isoformat(),
                "longitude": lng,
                "latitude": lat,
                "temperature": temp,
                "humidity": hum,
                "status": "运输中",
            }
            client.post("/api/transport/telemetry", json=t_payload, headers=_headers(tokens["transport01"]))

    # 6. 施工单位登记进场（部分不合格）
    for c in components:
        acceptance = "合格" if random.random() > args.unpassed_ratio else "不合格"
        entry_payload = {
            "component_id": c["id"],
            "entered_at": (now - timedelta(days=random.randint(5, 8))).isoformat(),
            "stack_location": f"A区堆场B{random.randint(1, 5)}-{random.randint(1, 30):02d}",
            "inspector": random.choice(["王工", "陈工", "赵工", "孙工"]),
            "acceptance": acceptance,
            "remark": "外观良好" if acceptance == "合格" else "外观破损 1~2 处",
            "photo_urls": [],
        }
        client.post("/api/site/entry", json=entry_payload, headers=_headers(tokens["contractor01"]))

    # 7. 吊装：仅对合格件
    for c in components:
        if random.random() < 0.05:
            continue  # 部分还未吊装
        hoist_payload = {
            "component_id": c["id"],
            "hoisted_at": (now - timedelta(days=random.randint(2, 5))).isoformat(),
            "equipment_no": random.choice(EQUIPMENT_POOL),
            "signal_worker": random.choice(["李工", "周工", "吴工"]),
            "rigger": random.choice(["赵师傅", "钱师傅", "孙师傅"]),
            "coord_lng": 119.965 + random.uniform(-0.001, 0.001),
            "coord_lat": 30.276 + random.uniform(-0.001, 0.001),
            "result": random.choice(["一次就位", "一次就位", "一次就位", "调整后到位"]),
        }
        r = client.post("/api/site/hoisting", json=hoist_payload, headers=_headers(tokens["contractor01"]))
        if r.status_code >= 400:
            # 不合格件被拒绝属于预期
            print(f"[模拟器] 吊装被拒绝（预期）: {c['trace_code']} -> {r.json().get('detail')}")

    # 8. 节点连接（仅对已吊装合格件）
    for c in components:
        joint_payload = {
            "component_id": c["id"],
            "grout_at": (now - timedelta(days=random.randint(1, 3))).isoformat(),
            "grout_batch": f"GB-2025-SIM{random.randint(0, 999):03d}",
            "bedding_at": (now - timedelta(days=random.randint(1, 3), hours=2)).isoformat(),
            "connection_type": random.choice(["灌浆套筒", "灌浆座浆", "后浇连接", "焊接连接"]),
            "operator": random.choice(["孙师傅", "周师傅", "吴师傅"]),
            "photo_urls": [],
        }
        r = client.post("/api/site/joint", json=joint_payload, headers=_headers(tokens["contractor01"]))
        if r.status_code >= 400:
            continue  # 未吊装或已存在则跳过

    # 9. 隐蔽验收
    for c in components:
        concealed_payload = {
            "component_id": c["id"],
            "accepted_at": (now - timedelta(days=random.randint(0, 2))).isoformat(),
            "quality_grade": random.choice(["合格", "合格", "优良"]),
            "inspector": random.choice(["刘监理", "周监理", "王监理"]),
            "photo_urls": [],
            "conclusion": "灌浆饱满、套筒连接到位",
        }
        r = client.post("/api/site/concealed", json=concealed_payload, headers=_headers(tokens["supervisor01"]))
        if r.status_code >= 400:
            continue

    # 10. 成品保护 + 风险提示
    for c in components:
        mep_choice = random.choice(["待机电", "电管预埋", "电焊切割", "通风安装"])
        measures = "已贴保护膜"
        protection_payload = {
            "component_id": c["id"],
            "decoration": "待装饰",
            "mep": mep_choice,
            "measures": measures,
        }
        r = client.post("/api/site/protection", json=protection_payload, headers=_headers(tokens["contractor01"]))
        if r.status_code >= 400:
            continue

    # 11. 离线同步：模拟弱网缓存批量回传
    sync_items = []
    for c in components[:5]:
        sync_items.append(
            {
                "event_type": "hoisting",
                "occurred_at": (now - timedelta(days=3)).isoformat(),
                "client_id": "FIELD-SCANNER-01",
                "payload": {
                    "component_id": c["id"],
                    "hoisted_at": (now - timedelta(days=3)).isoformat(),
                    "equipment_no": "TC7007-OFFLINE",
                    "signal_worker": "离线信号工",
                    "rigger": "离线司索工",
                    "coord_lng": 119.965,
                    "coord_lat": 30.276,
                    "result": "一次就位",
                },
            }
        )
    sync_payload = {"client_id": "FIELD-SCANNER-01", "batch_id": f"batch-{int(time.time())}", "items": sync_items}
    r = client.post("/api/sync/batch", json=sync_payload, headers=_headers(tokens["contractor01"]))
    print(f"[模拟器] 离线批量回传：{r.status_code} -> {r.json()}")

    # 12. 生成 + 导出档案
    for c in components[:5]:
        r = client.post(f"/api/archives/generate/{c['id']}", headers=_headers(tokens["owner01"]))
        r.raise_for_status()
        archive = r.json()
        print(f"[模拟器] 已生成档案 {archive['archive_no']} for {c['trace_code']}")

    # 13. 报送档案（向质量监督机构）
    archives = client.get("/api/archives", headers=_headers(tokens["owner01"])).json()
    for a in archives[:3]:
        r = client.post(f"/api/archives/{a['id']}/submit", headers=_headers(tokens["owner01"]))
        print(f"[模拟器] 报送档案 {a['archive_no']} -> {r.status_code}")

    print(f"\n[模拟器] 完成！已灌入 {len(components)} 个构件的全流程数据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
