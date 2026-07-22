#!/usr/bin/env bash
# 一键启动：构建并启动所有服务
set -e

cd "$(dirname "$0")"

echo "[1/4] 拉取并构建镜像..."
docker compose pull postgres redis 2>/dev/null || true
docker compose build backend frontend simulator

echo "[2/4] 启动容器栈..."
docker compose up -d postgres redis
echo "等待 PostgreSQL/Redis 健康检查..."
sleep 5

docker compose up -d backend
echo "等待 Backend 启动并完成 bootstrap..."
for i in {1..30}; do
  if docker compose exec -T backend curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "Backend 已就绪"
    break
  fi
  sleep 2
done

docker compose up -d frontend
echo "等待 Frontend 启动..."
sleep 5

echo "[3/4] 注入模拟数据..."
docker compose up simulator || true

echo "[4/4] 执行自检..."
docker compose exec -T backend python -m app.self_check || true

echo ""
echo "==========================================="
echo "服务已全部启动："
echo "  前端门户:    http://localhost:5173"
echo "  后端 API:    http://localhost:8000/docs"
echo "  默认账号:    factory01 / transport01 / contractor01 / supervisor01 / owner01 / quality01"
echo "  默认密码:    123456"
echo "==========================================="
