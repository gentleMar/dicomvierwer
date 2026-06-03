"""
DICOM API 路由
处理 DICOM 元数据读取和图像渲染
"""

from fastapi import APIRouter, HTTPException, status, Query
from fastapi.responses import StreamingResponse
import threading
import base64

from app.models.schemas import (
    DICOMMetadata,
    DICOMReportResponse,
    DICOMFrameSeriesResponse,
    DICOMFrameItem,
    DICOMAnalysisResponse,
    DICOMAnalysisRegion,
    DICOMAnalysisModeItem,
)
from app.services.dicom_service import DICOMService
from app.services.image_analysis import ImageAnalysisService
from app.services.region_extraction import list_region_extractors, DEFAULT_MODE
from app.services.ocr_backends import list_ocr_backends
from app.services.file_service import FileService
from app.auth.security import get_current_user
from app.auth.models import User
from app.config import settings


router = APIRouter(prefix="/api/dicom", tags=["dicom"])

# 初始化服务
dicom_service = DICOMService()
file_service = FileService(settings.get_base_dir())


def _resolve_dicom_source(path: str):
    """Resolve DICOM source from disk or remote fetch according to current mode.

    Returns either a Path or bytes.
    """
    full_path = file_service.get_full_path(path)

    if full_path.exists() and full_path.is_file():
        return full_path

    from app.services import remote_sync

    # Always try on-demand fetch when local file is absent.
    remote_sync.fetch_remote_file(path)

    if settings.fetch_mode == "memory":
        return remote_sync.get_memory_bytes(path)

    # disk mode: fetch_remote_file already wrote to disk
    if full_path.exists() and full_path.is_file():
        return full_path

    raise ValueError("File not found")


@router.get("/metadata")
async def get_dicom_metadata(
    path: str = Query(..., description="DICOM 文件相对路径"),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> DICOMMetadata:
    """
    读取 DICOM 元数据
    
    Args:
        path: DICOM 文件相对路径
        current_user: 当前用户
        
    Returns:
        DICOM 元数据
    """
    try:
        source = _resolve_dicom_source(path)
        metadata = DICOMService.read_metadata(source)
        return metadata
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/image")
async def get_dicom_image(
    path: str = Query(..., description="DICOM 文件相对路径"),
    frame: int = Query(0, ge=0, description="帧索引"),
    format: str = Query("png", regex="^(png|jpeg)$", description="图像格式"),
    quality: int = Query(90, ge=1, le=100, description="JPEG 质量"),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> StreamingResponse:
    """
    获取 DICOM 图像
    
    Args:
        path: DICOM 文件相对路径
        frame: 帧索引（多帧图像）
        format: 图像格式（png 或 jpeg）
        quality: JPEG 质量
        current_user: 当前用户
        
    Returns:
        图像流
    """
    try:
        source = _resolve_dicom_source(path)

        # 渲染图像
        if format == "png":
            image_data = DICOMService.render_to_png(source, frame)
            media_type = "image/png"
        else:  # jpeg
            image_data = DICOMService.render_to_jpeg(source, frame, quality)
            media_type = "image/jpeg"

        try:
            metadata = DICOMService.read_metadata(source)
            threading.Thread(
                target=DICOMService.prefetch_rendered_frames,
                args=(source, frame, metadata.number_of_frames or 1, format, quality),
                daemon=True,
            ).start()
        except Exception:
            pass
        
        return StreamingResponse(
            iter([image_data]),
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename=dicom.{format}"}
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/frames", response_model=DICOMFrameSeriesResponse)
async def get_dicom_frames(
    path: str = Query(..., description="DICOM 文件相对路径"),
    format: str = Query("png", regex="^(png|jpeg)$", description="图像格式"),
    quality: int = Query(90, ge=1, le=100, description="JPEG 质量"),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> DICOMFrameSeriesResponse:
    """一次性返回整套多帧图像，供浏览器本地切帧使用。"""
    try:
        source = _resolve_dicom_source(path)
        metadata = DICOMService.read_metadata(source)
        frame_count = metadata.number_of_frames or 1

        frames = []
        for frame_index in range(frame_count):
            if format == "png":
                image_data = DICOMService.render_to_png(source, frame_index)
            else:
                image_data = DICOMService.render_to_jpeg(source, frame_index, quality)
            encoded = base64.b64encode(image_data).decode("ascii")
            frames.append(DICOMFrameItem(frame=frame_index, data=encoded))

        return DICOMFrameSeriesResponse(
            path=path,
            format=format,
            frame_count=frame_count,
            width=metadata.columns,
            height=metadata.rows,
            frames=frames,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/report", response_model=DICOMReportResponse)
async def get_dicom_report(
    path: str = Query(..., description="DICOM 文件相对路径"),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> DICOMReportResponse:
    """获取 SR 结构化报告正文"""
    try:
        source = _resolve_dicom_source(path)
        report = DICOMService.extract_structured_report(source)
        return DICOMReportResponse(
            path=path,
            modality=report.get("modality"),
            title=report.get("title"),
            text=report.get("text", ""),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/analyze", response_model=DICOMAnalysisResponse)
async def analyze_dicom_image(
    path: str = Query(..., description="DICOM 文件相对路径"),
    frame: int = Query(0, ge=0, description="帧索引"),
    ocr_lang: str = Query("chi_sim+eng", description="OCR 语言"),
    mode: str = Query(DEFAULT_MODE, description="影像区域提取方式"),
    ocr_engine: str = Query("tesseract", description="OCR 引擎（tesseract 或 paddleocr_cpu）"),
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> DICOMAnalysisResponse:
    """对当前展示的 DICOM 图像执行 OCR + OpenCV 分析。"""
    try:
        source = _resolve_dicom_source(path)
        image_bytes = DICOMService.render_to_png(source, frame)
        result = ImageAnalysisService.analyze_png_bytes(image_bytes, ocr_lang=ocr_lang, mode=mode, ocr_engine=ocr_engine)

        regions = [
            DICOMAnalysisRegion(**region)
            for region in result.get("regions", [])
        ]

        return DICOMAnalysisResponse(
            path=path,
            mode=result.get("mode", mode),
            frame=frame,
            text=result.get("text", ""),
            diagnosis_opinions=result.get("diagnosis_opinions", []),
            regions=regions,
            warnings=result.get("warnings", []),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/analyze/modes", response_model=list[DICOMAnalysisModeItem])
async def list_analysis_modes(
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> list[DICOMAnalysisModeItem]:
    """返回当前可用的图像区域提取方式，供前端下拉选择。"""
    return [DICOMAnalysisModeItem(**item) for item in list_region_extractors()]


@router.get("/analyze/engines")
async def list_ocr_engines(
    current_user: User = __import__("fastapi").Depends(get_current_user)
) -> list:
    """返回可用的 OCR 引擎列表供前端选择（非鉴权信息）。"""
    return list_ocr_backends()
