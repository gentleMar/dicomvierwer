"""
Pydantic Schema 定义
用于 API 请求/响应的数据验证
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ============ 认证相关 ============

class TokenResponse(BaseModel):
    """令牌响应"""
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    """用户响应"""
    username: str
    email: Optional[str] = None
    disabled: bool = False


# ============ 文件相关 ============

class FileItem(BaseModel):
    """文件项"""
    name: str
    path: str
    is_dir: bool
    is_dicom: bool = False
    size: Optional[int] = None
    modified_time: Optional[datetime] = None


class DirectoryContent(BaseModel):
    """目录内容"""
    path: str
    items: List[FileItem]
    total: int = 0


# ============ DICOM 相关 ============

class DICOMMetadata(BaseModel):
    """DICOM 元数据"""
    patient_name: Optional[str] = None
    patient_id: Optional[str] = None
    study_date: Optional[str] = None
    modality: Optional[str] = None
    series_description: Optional[str] = None
    instance_number: Optional[int] = None
    rows: Optional[int] = None
    columns: Optional[int] = None
    bits_allocated: Optional[int] = None
    bits_stored: Optional[int] = None
    high_bit: Optional[int] = None
    pixel_representation: Optional[int] = None
    number_of_frames: Optional[int] = None
    photometric_interpretation: Optional[str] = None
    raw_metadata: Optional[Dict[str, Any]] = None


class DICOMImageResponse(BaseModel):
    """DICOM 图像响应"""
    path: str
    format: str = "png"
    frame: int = 0
    width: int
    height: int


class DICOMFrameItem(BaseModel):
    """单帧图像数据"""
    frame: int
    data: str


class DICOMFrameSeriesResponse(BaseModel):
    """整系列帧图像响应"""
    path: str
    format: str = "png"
    frame_count: int
    width: Optional[int] = None
    height: Optional[int] = None
    frames: List[DICOMFrameItem]


class DICOMReportResponse(BaseModel):
    """DICOM 结构化报告响应"""
    path: str
    modality: Optional[str] = None
    title: Optional[str] = None
    text: str


class DICOMAnalysisRegion(BaseModel):
    """解析到的图像区域"""
    index: int
    x: int
    y: int
    width: int
    height: int
    area_ratio: float
    ocr_text: Optional[str] = None
    image_base64: str


class DICOMAnalysisResponse(BaseModel):
    """OCR + OpenCV 图像分析响应"""
    path: str
    mode: Optional[str] = None
    frame: int = 0
    text: str = ""
    diagnosis_opinions: List[str] = Field(default_factory=list)
    regions: List[DICOMAnalysisRegion] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DICOMAnalysisModeItem(BaseModel):
    """图像区域提取模式"""
    mode: str
    label: str
    description: Optional[str] = None


# ============ API 响应 ============

class APIResponse(BaseModel):
    """通用 API 响应"""
    code: int = 200
    message: str = "Success"
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = 400
    message: str
    detail: Optional[str] = None
