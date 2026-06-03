"""
主应用程序
FastAPI 应用的入口点
"""

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import auth, files, dicom
from app.api import sync
from app.services.auth_service import AuthService


# ============ 启动事件 ============

def init_app():
    """初始化应用"""
    # 检查 DICOM 基础目录
    base_dir = settings.get_base_dir()
    if not base_dir.exists():
        print(f"⚠️  DICOM 基础目录不存在: {base_dir}")
        print("   请创建该目录或配置 LOCAL_SYNC_DIR 环境变量")
    else:
        print(f"✓ DICOM 基础目录: {base_dir}")
    
    # 创建默认用户
    try:
        # 检查默认用户是否存在
        if settings.default_username:
            existing_user = AuthService.get_user(settings.default_username)
            if existing_user is None:
                AuthService.register(
                    settings.default_username,
                    settings.default_password
                )
                print(f"✓ 创建默认用户: {settings.default_username}")
            else:
                print(f"✓ 默认用户已存在: {settings.default_username}")
    except Exception as e:
        print(f"⚠️  创建默认用户失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    print("🚀 应用启动...")
    init_app()
    yield
    # 关闭
    print("🛑 应用关闭...")


# ============ 创建应用 ============

app = FastAPI(
    title="DICOM Viewer",
    description="基于 Python 的远程 DICOM 文件浏览与查看系统",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ============ CORS 中间件 ============

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 注册路由 ============

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(dicom.router)
app.include_router(sync.router)

# ============ 静态文件 ============

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static"
)

# ============ 主页面 ============

@app.get("/")
async def root():
    """主页面"""
    return FileResponse(
        "app/templates/index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


# ============ 健康检查 ============

@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "0.1.0"
    }


# ============ 错误处理 ============

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    return {
        "code": 500,
        "message": "Internal server error",
        "detail": str(exc) if settings.debug else None
    }


# ============ 应用入口 ============

if __name__ == "__main__":
    import uvicorn
    
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║        DICOM Viewer - 远程 DICOM 文件浏览系统            ║
    ║                                                          ║
    ║  服务地址: http://{settings.host}:{settings.port}
    ║  文档: http://{settings.host}:{settings.port}/api/docs
    ║                                                          ║
    ║  按 Ctrl+C 停止服务                                      ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info",
    )
