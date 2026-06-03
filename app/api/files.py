"""
文件浏览 API 路由
处理目录浏览、文件列表等
"""

from fastapi import APIRouter, HTTPException, status, Query

from pathlib import Path
from app.models.schemas import DirectoryContent, FileItem
from app.services.file_service import FileService
from app.services import remote_sync
from app.config import settings
from app.auth.security import get_current_user
from app.auth.models import User
from app.config import settings


router = APIRouter(prefix="/api/files", tags=["files"])

# 初始化文件服务
file_service = FileService(settings.get_base_dir())


@router.get("/list")
async def list_directory(
    path: str = Query("", description="相对路径"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> DirectoryContent:
    """
    列出目录内容
    
    Args:
        path: 相对路径
        skip: 跳过的项数
        limit: 返回的项数限制
        current_user: 当前用户
        
    Returns:
        目录内容
    """
    # 优先返回远端目录结构（不拷贝文件）。当远端不可用时回退到本地目录（LOCAL_SYNC_DIR）。
    try:
        try:
            remote_dir = remote_sync.list_remote(path)
            return remote_dir
        except Exception:
            # 无法获取远端目录时，回退到本地目录
            return file_service.list_directory(path, skip, limit)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )


@router.get("/info")
async def get_file_info(
    path: str = Query(..., description="相对路径"),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> FileItem:
    """
    获取文件信息
    
    Args:
        path: 相对路径
        current_user: 当前用户
        
    Returns:
        文件信息
    """
    # 优先使用本地已存在的文件；若本地不存在且远端可用，则按需拉取后返回信息
    try:
        if file_service.file_exists(path):
            return file_service.get_file_info(path)

        # 本地不存在，根据 fetch_mode 处理
        if settings.fetch_mode == "memory":
            try:
                remote_sync.fetch_remote_file(path)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

            try:
                data = remote_sync.get_memory_bytes(path)
                from app.services.dicom_service import DICOMService
                # 读取元数据以验证并构造 FileItem
                _ = DICOMService.read_metadata(data)
                return FileItem(
                    name=Path(path).name,
                    path=path,
                    is_dir=False,
                    is_dicom=True,
                    size=len(data),
                    modified_time=None,
                )
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

        # disk 模式：拉取到本地后返回文件信息
        try:
            remote_sync.fetch_remote_file(path)
            return file_service.get_file_info(path)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
