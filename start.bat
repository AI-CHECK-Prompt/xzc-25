@echo off
REM 一键启动：构建并启动所有服务（Windows 友好）
cd /d "%~dp0"

echo [1/4] 构建镜像...
docker compose build backend frontend simulator
if errorlevel 1 goto :err

echo [2/4] 启动容器栈...
docker compose up -d postgres redis
timeout /t 5 /nobreak > nul
docker compose up -d backend
echo 等待 Backend 就绪...
:wait_backend
docker compose exec -T backend curl -s http://localhost:8000/ > nul 2>&1
if errorlevel 1 (
  timeout /t 2 /nobreak > nul
  goto :wait_backend
)
docker compose up -d frontend
timeout /t 5 /nobreak > nul

echo [3/4] 注入模拟数据...
docker compose up simulator

echo [4/4] 执行自检...
docker compose exec -T backend python -m app.self_check

echo.
echo ===========================================
echo 服务已全部启动：
echo   前端门户:    http://localhost:5173
echo   后端 API:    http://localhost:8000/docs
echo   默认密码:    123456
echo ===========================================
exit /b 0

:err
echo 启动失败
exit /b 1
