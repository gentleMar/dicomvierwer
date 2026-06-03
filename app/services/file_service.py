"""
文件服务模块
处理文件系统浏览和操作
"""

from pathlib import Path
from typing import List, Optional
from datetime import datetime

from app.utils.path_utils import PathValidator
from app.models.schemas import FileItem, DirectoryContent


class FileService:
    """文件服务"""
    
    def __init__(self, base_dir: Path):
        """
        初始化文件服务
        
        Args:
            base_dir: 基础目录
        """
        self.base_dir = base_dir.resolve()
        self.validator = PathValidator(self.base_dir)
    
    def list_directory(
        self,
        rel_path: str = "",
        skip: int = 0,
        limit: int = 100
    ) -> DirectoryContent:
        """
        列出目录内容
        
        Args:
            rel_path: 相对路径
            skip: 跳过的项数
            limit: 限制的项数
            
        Returns:
            目录内容
            
        Raises:
            ValueError: 路径不安全或不是目录
        """
        # 验证路径
        full_path = self.validator.validate_path(rel_path)
        
        # 检查是否是目录
        if not full_path.is_dir():
            raise ValueError(f"Path is not a directory: {rel_path}")
        
        # 列出文件
        items: List[FileItem] = []
        try:
            for entry in full_path.iterdir():
                try:
                    item = self._create_file_item(entry)
                    items.append(item)
                except Exception:
                    # 忽略无法读取的文件
                    continue
        except PermissionError:
            raise ValueError(f"Permission denied: {rel_path}")
        
        # 排序：目录优先
        items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
        
        # 分页
        total = len(items)
        paginated_items = items[skip : skip + limit]
        
        # 计算相对路径
        if full_path == self.base_dir:
            display_path = "/"
        else:
            display_path = "/" + str(full_path.relative_to(self.base_dir)).replace("\\", "/")
        
        return DirectoryContent(
            path=display_path,
            items=paginated_items,
            total=total
        )
    
    def get_file_info(self, rel_path: str) -> FileItem:
        """
        获取文件信息
        
        Args:
            rel_path: 相对路径
            
        Returns:
            文件信息
        """
        full_path = self.validator.validate_path(rel_path)
        
        if not full_path.exists():
            raise ValueError(f"File not found: {rel_path}")
        
        return self._create_file_item(full_path)
    
    def _create_file_item(self, path: Path) -> FileItem:
        """
        创建文件项
        
        Args:
            path: 文件路径
            
        Returns:
            文件项
        """
        # 计算相对路径
        try:
            rel_path = path.relative_to(self.base_dir)
            display_path = "/" + str(rel_path).replace("\\", "/")
        except ValueError:
            display_path = path.name
        
        # 检查是否是目录
        is_dir = path.is_dir()
        
        # 检查是否是 DICOM 文件
        is_dicom = False
        if not is_dir:
            is_dicom = self.validator.is_dicom_file(path)
        
        # 获取文件大小
        try:
            size = path.stat().st_size if not is_dir else None
        except Exception:
            size = None
        
        # 获取修改时间
        try:
            modified_time = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            modified_time = None
        
        return FileItem(
            name=path.name,
            path=display_path,
            is_dir=is_dir,
            is_dicom=is_dicom,
            size=size,
            modified_time=modified_time
        )
    
    def file_exists(self, rel_path: str) -> bool:
        """
        检查文件是否存在
        
        Args:
            rel_path: 相对路径
            
        Returns:
            文件是否存在
        """
        try:
            full_path = self.validator.validate_path(rel_path)
            return full_path.exists()
        except ValueError:
            return False
    
    def get_full_path(self, rel_path: str) -> Path:
        """
        获取完整路径
        
        Args:
            rel_path: 相对路径
            
        Returns:
            完整路径
        """
        return self.validator.validate_path(rel_path)
