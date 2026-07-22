# 装配式建筑构件全过程质量追溯平台

面向预制构件工厂、运输单位、施工总承包、监理、建设单位、质量监督机构六方协同，覆盖构件生产 → 出厂 → 运输 → 进场 → 吊装 → 节点连接 → 隐蔽验收 → 成品保护 → 档案归档全链路。

## 1. 技术栈

| 层 | 选型 | 用途 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI + SQLAlchemy | REST API、权限、追溯聚合 |
| 数据库 | PostgreSQL 15 | 业务数据、唯一追溯码索引 |
| 缓存/队列 | Redis 7 | 离线同步队列、温湿度越界判定 |
| 前端 | Vue3 + Vite + TypeScript + Element Plus | 参与方工作台、追溯查询 |
| 模拟器 | Python 3.11 | 批量注入全流程数据 |
| 编排 | Docker Compose | 一键启动、零到一交付 |

## 2. 一键启动

```bash
docker compose up -d --build
```

启动后访问：

- 前端门户: <http://localhost:5173>
- 后端 API 文档: <http://localhost:8000/docs>
- 模拟器自动注入 1 个完整工地项目的全流程数据，可在日志中观察

## 3. 默认账号

| 账号 | 角色 | 密码 |
|---|---|---|
| factory01 | 预制构件工厂 | 123456 |
| transport01 | 运输单位 | 123456 |
| contractor01 | 施工总承包 | 123456 |
| supervisor01 | 监理单位 | 123456 |
| owner01 | 建设单位 | 123456 |
| quality01 | 质量监督机构 | 123456 |

## 4. 四类追溯验收场景

1. **容器栈启动后批量注入**：`simulator/inject_data.py` 在 backend 就绪后向 1 个工地项目注入 30 件构件的全链路记录。
2. **构件追溯查询**：在「构件追溯」界面输入追溯码或扫描二维码，查看生产→出厂→运输→进场→吊装→节点→隐蔽→保护→档案的完整时间线。
3. **不合格件不可吊装**：进场验收结论为「不合格」的构件，在吊装环节调用 `/api/hoisting` 时被后端拒绝。
4. **档案归档导出与报送**：在「档案归档」界面可下载符合城建档案规范的电子档案包（ZIP），并通过 `/api/archives/{id}/submit` 推送到质量监督机构。

## 5. 离线缓存

工地现场扫码终端（浏览器实现）使用 IndexedDB 缓存扫码事件，弱网时存入本地队列，恢复网络后自动批量同步至后端 `POST /api/sync/batch`。

## 6. 唯一追溯码

每个构件生成形如 `PC-YYYYMMDD-{工厂代码}-{序列号}` 的编码，兼容二维码与 RFID 标签两种形态（前端用 `qrcode` 与 `nfc` 占位字段，前端只读扫描器输入的字符串即可）。

## 7. 目录结构

```
.
├── docker-compose.yml
├── .gitignore
├── backend/                # FastAPI 服务
│   ├── app/                # 业务代码
│   ├── sql/init.sql        # 初始表结构（备份）
│   └── Dockerfile
├── frontend/               # Vue3 工作台
│   ├── src/
│   └── Dockerfile
├── simulator/              # 数据注入模拟器
│   └── inject_data.py
└── docs/                   # 验收报告与说明
```

## 8. 自检

```bash
docker compose exec backend python -m app.self_check
```

输出验收场景 1~4 的 PASS/FAIL 汇总。
