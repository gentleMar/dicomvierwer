"""
认证数据模型
定义用户和认证相关的数据结构
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    """用户模型"""
    username: str
    email: Optional[str] = None
    disabled: bool = False
    
    def __post_init__(self):
        """验证用户数据"""
        if not self.username:
            raise ValueError("Username cannot be empty")


@dataclass
class UserInDB:
    """数据库中的用户模型"""
    username: str
    hashed_password: str
    email: Optional[str] = None
    disabled: bool = False
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Token:
    """访问令牌模型"""
    access_token: str
    token_type: str = "bearer"


@dataclass
class TokenData:
    """令牌数据模型"""
    username: Optional[str] = None
    exp: Optional[datetime] = None
