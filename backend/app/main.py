"""FastAPI 入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .bootstrap import ensure_seed
from .db import Base, engine
from .routes import archives, auth, components, meta, quality, site, sync, trace, transport


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建表 + 灌入种子数据
    Base.metadata.create_all(bind=engine)
    ensure_seed()
    yield


app = FastAPI(
    title="装配式建筑构件全过程质量追溯平台",
    version="1.0.0",
    description="工厂、运输、施工、监理、建设、质监六方协同，覆盖构件全生命周期。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["健康检查"])
def health():
    return {
        "service": "装配式建筑构件追溯平台",
        "status": "ok",
        "version": "1.0.0",
    }


app.include_router(auth.router)
app.include_router(components.router)
app.include_router(transport.router)
app.include_router(site.router)
app.include_router(archives.router)
app.include_router(trace.router)
app.include_router(sync.router)
app.include_router(meta.router)
app.include_router(quality.router)
