"""
远程同步相关 API 路由

提供：
- `/api/sync/refresh`：仅同步远程目录结构（不拷贝文件），用于刷新前端目录树
- `/api/sync/fetch`：按需拉取单个远程文件到本地 `LOCAL_SYNC_DIR`
"""
from fastapi import APIRouter, HTTPException, status, Query

from app.auth.security import get_current_user
from app.auth.models import User
from app.config import settings
from app.services.remote_sync import list_remote, fetch_remote_file
from app.services.remote_sync import clear_memory_cache, memory_cache_stats
from app.services.dicom_service import DICOMService
from app.models.schemas import DirectoryContent


router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/refresh", response_model=DirectoryContent)
async def refresh_remote(path: str = Query("", description="相对路径"), current_user: User = __import__("fastapi").Depends(get_current_user)) -> DirectoryContent:
    """列出远程目录结构（不传输文件）"""
    try:
        return list_remote(path)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/fetch")
async def fetch_file(path: str = Query(..., description="相对路径"), current_user: User = __import__("fastapi").Depends(get_current_user)):
    """按需拉取单个远程文件到本地 `LOCAL_SYNC_DIR`，返回本地路径"""
    try:
        local_path = fetch_remote_file(path)
        return {"local_path": str(local_path)}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post('/cache/clear')
async def clear_cache(current_user: User = __import__("fastapi").Depends(get_current_user)):
    try:
        clear_memory_cache()
        DICOMService.clear_rendered_cache()
        return {"cleared": True}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get('/cache/status')
async def cache_status(current_user: User = __import__("fastapi").Depends(get_current_user)):
    try:
        stats = memory_cache_stats()
        stats["fetch_mode"] = settings.fetch_mode
        stats["render_cache"] = DICOMService.rendered_cache_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
