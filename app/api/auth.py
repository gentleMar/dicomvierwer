"""
认证 API 路由
处理登录、注册等认证相关的 API
"""

from fastapi import APIRouter, HTTPException, status

from app.models.schemas import LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService
from app.auth.security import get_current_user
from app.auth.models import User


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    用户登录
    
    Args:
        request: 登录请求
        
    Returns:
        访问令牌
    """
    # 验证用户
    token = AuthService.authenticate(request.username, request.password)
    
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    return TokenResponse(access_token=token)


@router.post("/register", response_model=UserResponse)
async def register(request: LoginRequest):
    """
    用户注册
    
    Args:
        request: 注册请求
        
    Returns:
        创建的用户信息
    """
    try:
        user = AuthService.register(request.username, request.password)
        return UserResponse(username=user.username, email=user.email)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = __import__("fastapi").Depends(get_current_user)):
    """
    获取当前用户信息
    
    Args:
        current_user: 当前用户
        
    Returns:
        用户信息
    """
    return UserResponse(
        username=current_user.username,
        email=current_user.email,
        disabled=current_user.disabled
    )
