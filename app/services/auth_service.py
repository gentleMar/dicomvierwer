"""
认证服务模块
处理用户认证逻辑
"""

from typing import Optional
from datetime import timedelta

from app.auth.security import SecurityService, UserStore
from app.auth.models import UserInDB


class AuthService:
    """认证服务"""
    
    @staticmethod
    def authenticate(username: str, password: str) -> Optional[str]:
        """
        认证用户并返回访问令牌
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            访问令牌，失败返回 None
        """
        user = UserStore.authenticate_user(username, password)
        if user is None:
            return None
        
        # 创建访问令牌
        access_token = SecurityService.create_access_token(
            data={"sub": user.username}
        )
        return access_token
    
    @staticmethod
    def register(username: str, password: str, email: Optional[str] = None) -> UserInDB:
        """
        注册新用户
        
        Args:
            username: 用户名
            password: 密码
            email: 邮箱（可选）
            
        Returns:
            创建的用户对象
        """
        return UserStore.create_user(username, password, email)
    
    @staticmethod
    def get_user(username: str) -> Optional[UserInDB]:
        """
        获取用户信息
        
        Args:
            username: 用户名
            
        Returns:
            用户对象，不存在返回 None
        """
        return UserStore.get_user(username)
