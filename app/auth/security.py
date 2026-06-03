"""
安全工具模块
- 密码哈希和验证
- JWT 令牌管理
- 用户认证
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path
import json

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.hash import pbkdf2_sha256

from app.config import settings
from app.auth.models import User, UserInDB, TokenData


# OAuth2 认证方案
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# 用户存储文件（简单实现，实际应使用数据库）
USERS_FILE = Path(__file__).parent.parent / "data" / "users.json"


class SecurityService:
    """安全服务"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        哈希密码
        
        Args:
            password: 明文密码
            
        Returns:
            哈希后的密码
        """
        return pbkdf2_sha256.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        验证密码
        
        Args:
            plain_password: 明文密码
            hashed_password: 哈希密码
            
        Returns:
            密码是否正确
        """
        if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
            try:
                from passlib.hash import bcrypt

                return bcrypt.verify(plain_password, hashed_password)
            except Exception:
                return False

        try:
            return pbkdf2_sha256.verify(plain_password, hashed_password)
        except Exception:
            return False
    
    @staticmethod
    def create_access_token(
        data: dict, 
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        创建访问令牌
        
        Args:
            data: 令牌中的数据
            expires_delta: 过期时间差
            
        Returns:
            JWT 令牌
        """
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=settings.access_token_expire_minutes
            )
        
        to_encode.update({"exp": expire})
        
        encoded_jwt = jwt.encode(
            to_encode,
            settings.secret_key,
            algorithm=settings.algorithm
        )
        
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> TokenData:
        """
        验证 JWT 令牌
        
        Args:
            token: JWT 令牌
            
        Returns:
            令牌数据
            
        Raises:
            HTTPException: 令牌无效
        """
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm]
            )
            username: str = payload.get("sub")
            if username is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token"
                )
            return TokenData(username=username)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )


class UserStore:
    """用户存储服务（简单实现）"""
    
    @staticmethod
    def ensure_users_file():
        """确保用户文件存在"""
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not USERS_FILE.exists():
            USERS_FILE.write_text(json.dumps({}))
    
    @staticmethod
    def load_users() -> dict:
        """加载所有用户"""
        UserStore.ensure_users_file()
        try:
            return json.loads(USERS_FILE.read_text())
        except Exception:
            return {}
    
    @staticmethod
    def save_users(users: dict):
        """保存用户"""
        UserStore.ensure_users_file()
        USERS_FILE.write_text(json.dumps(users, indent=2))
    
    @staticmethod
    def get_user(username: str) -> Optional[UserInDB]:
        """获取用户"""
        users = UserStore.load_users()
        user_data = users.get(username)
        if user_data is None:
            return None
        return UserInDB(**user_data)
    
    @staticmethod
    def create_user(username: str, password: str, email: Optional[str] = None) -> UserInDB:
        """
        创建用户
        
        Args:
            username: 用户名
            password: 明文密码
            email: 邮箱（可选）
            
        Returns:
            创建的用户对象
        """
        users = UserStore.load_users()
        
        if username in users:
            raise ValueError(f"User {username} already exists")
        
        hashed_password = SecurityService.hash_password(password)
        user = UserInDB(
            username=username,
            hashed_password=hashed_password,
            email=email
        )
        
        users[username] = {
            "username": user.username,
            "hashed_password": user.hashed_password,
            "email": user.email,
            "disabled": user.disabled,
            "created_at": user.created_at.isoformat()
        }
        
        UserStore.save_users(users)
        return user
    
    @staticmethod
    def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
        """
        认证用户
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            认证成功的用户对象，或 None
        """
        user = UserStore.get_user(username)
        if user is None:
            return None
        
        if not SecurityService.verify_password(password, user.hashed_password):
            return None
        
        return user


# 依赖注入：获取当前用户
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    获取当前认证用户
    
    Args:
        token: JWT 令牌
        
    Returns:
        当前用户
        
    Raises:
        HTTPException: 用户未认证或令牌无效
    """
    credential_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_data = SecurityService.verify_token(token)
    user = UserStore.get_user(username=token_data.username)
    
    if user is None:
        raise credential_exception
    
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User disabled")
    
    return User(username=user.username, email=user.email, disabled=user.disabled)
