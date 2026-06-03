"""
应用配置模块
- 从环境变量读取配置
- 提供类型安全的配置对象
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用设置"""
    
    # 应用信息
    app_name: str = "DICOM Viewer"
    debug: bool = False
    
    # 安全配置
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # 本机读取目录（由远端同步脚本或本机测试数据提供）
    local_sync_dir: Path = Path("./test-output")

    # 远端源配置（刷新目录树和按需拉取文件使用）
    remote_host: Optional[str] = None
    remote_user: Optional[str] = None
    remote_port: int = 22
    remote_dicom_dir: str = "~/dicom-data"
    # 拉取模式：'disk' 写入本地 LOCAL_SYNC_DIR；'memory' 只保存在内存（合规模式）
    fetch_mode: str = "disk"
    # 内存缓存配置（当 fetch_mode == 'memory' 时生效）
    memory_cache_max_bytes: int = 256 * 1024 * 1024  # 最大缓存字节数，默认 200MB
    memory_cache_max_items: int = 64  # 最大缓存条目数
    memory_cache_ttl_seconds: int = 60 * 60  # 缓存条目过期时长（秒），默认 1 小时
    memory_cache_eviction_policy: str = "lru"  # 淘汰策略，目前支持 'lru'
    render_cache_max_bytes: int = 256 * 1024 * 1024  # 渲染后图像缓存最大字节数
    render_cache_max_items: int = 128  # 渲染后图像缓存最大条目数
    render_cache_ttl_seconds: int = 30 * 60  # 渲染后图像缓存过期时长（秒）
    dataset_cache_max_items: int = 8  # 已解析 DICOM 数据集缓存条目数
    dataset_cache_ttl_seconds: int = 30 * 60  # 数据集缓存过期时长（秒）
    tesseract_cmd: Optional[str] = None  # OCR 引擎可执行文件路径（可选）
    analysis_max_regions: int = 20  # 单次解析最多返回的图像区域数量
    
    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    
    # 默认用户（用于初始化）
    default_username: Optional[str] = None
    default_password: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"
    
    def get_base_dir(self) -> Path:
        """获取本机读取目录的绝对路径"""
        return self.local_sync_dir.resolve()


# 全局设置实例
settings = Settings()
