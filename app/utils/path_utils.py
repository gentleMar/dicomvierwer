"""
路径工具模块
处理路径安全检查和操作
"""

from pathlib import Path
from typing import Optional
import os


class PathValidator:
    """路径验证器"""
    
    def __init__(self, base_dir: Path):
        """
        初始化路径验证器
        
        Args:
            base_dir: 基础目录
        """
        self.base_dir = base_dir.resolve()
    
    def validate_path(self, rel_path: str) -> Path:
        """
        验证路径，防止路径穿越攻击
        
        Args:
            rel_path: 相对路径
            
        Returns:
            验证后的绝对路径
            
        Raises:
            ValueError: 路径不安全
        """
        # 清理路径
        clean_path = str(rel_path).strip("/\\")
        if not clean_path:
            return self.base_dir
        
        # 构建完整路径
        full_path = (self.base_dir / clean_path).resolve()
        
        # 检查路径是否在基础目录内
        try:
            full_path.relative_to(self.base_dir)
        except ValueError:
            raise ValueError(f"Path traversal attempt detected: {rel_path}")
        
        return full_path
    
    def is_safe_path(self, rel_path: str) -> bool:
        """
        检查路径是否安全
        
        Args:
            rel_path: 相对路径
            
        Returns:
            路径是否安全
        """
        try:
            self.validate_path(rel_path)
            return True
        except ValueError:
            return False
    
    def is_dicom_file(self, path: Path) -> bool:
        """
        检查文件是否为 DICOM 文件
        
        Args:
            path: 文件路径
            
        Returns:
            是否为 DICOM 文件
        """
        if not path.is_file():
            return False
        
        # 检查文件扩展名
        suffix = path.suffix.lower()
        if suffix == ".dcm":
            return True
        
        # 检查文件魔数（DICOM 文件以 DICM 开头）
        try:
            with open(path, "rb") as f:
                # DICOM 文件的魔数在第 128 字节后
                f.seek(128)
                magic = f.read(4)
                return magic == b"DICM"
        except Exception:
            return False
    
    @staticmethod
    def is_safe_filename(filename: str) -> bool:
        """
        检查文件名是否安全
        
        Args:
            filename: 文件名
            
        Returns:
            文件名是否安全
        """
        # 禁止的字符
        forbidden_chars = ["<", ">", ":", '"', "|", "?", "*", "../", "..\\"]
        
        for char in forbidden_chars:
            if char in filename:
                return False
        
        return True
