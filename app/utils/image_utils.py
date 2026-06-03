"""
图像处理工具模块
处理 DICOM 图像转换为 PNG/JPEG
"""

from pathlib import Path
from typing import Optional, Tuple
import io

import numpy as np
from PIL import Image, ImageFile
from pydicom.pixel_data_handlers.util import convert_color_space

# 兼容某些压缩/截断图像数据，避免 PIL 在读取封装像素数据时直接抛出 broken data stream
ImageFile.LOAD_TRUNCATED_IMAGES = True


class ImageConverter:
    """图像转换器"""

    @staticmethod
    def convert_photometric_array(pixel_array: np.ndarray, photometric_interpretation: Optional[str] = None) -> np.ndarray:
        """Normalize DICOM color spaces to display-ready RGB when possible."""
        photometric = str(photometric_interpretation or "").upper()
        if pixel_array.ndim < 3:
            return pixel_array

        if photometric in {"YBR_FULL", "YBR_FULL_422"}:
            if pixel_array.shape[-1] == 3:
                try:
                    return convert_color_space(pixel_array, photometric, "RGB", per_frame=pixel_array.ndim == 4)
                except Exception:
                    return pixel_array

        if photometric == "YBR_RCT" and pixel_array.shape[-1] == 3:
            return ImageConverter.ybr_rct_to_rgb(pixel_array)

        return pixel_array

    @staticmethod
    def ybr_rct_to_rgb(pixel_array: np.ndarray) -> np.ndarray:
        """Convert JPEG 2000 reversible YBR_RCT data to RGB.

        Expected channel order: Y, Cb, Cr.
        """
        arr = np.asarray(pixel_array)
        if arr.ndim < 3 or arr.shape[-1] != 3:
            return arr

        work = arr.astype(np.int32, copy=False)
        y = work[..., 0]
        cb = work[..., 1]
        cr = work[..., 2]

        g = y - ((cb + cr) // 4)
        r = cr + g
        b = cb + g

        rgb = np.stack((r, g, b), axis=-1)
        return np.clip(rgb, 0, 255).astype(np.uint8)

    @staticmethod
    def _scale_to_uint8(pixel_array: np.ndarray) -> np.ndarray:
        if pixel_array.dtype == np.uint8:
            return pixel_array

        if np.issubdtype(pixel_array.dtype, np.integer):
            info = np.iinfo(pixel_array.dtype)
            if info.max <= 255 and info.min >= 0:
                return pixel_array.astype(np.uint8)

        pixel_array = pixel_array.astype(np.float32)
        min_val = float(np.min(pixel_array))
        max_val = float(np.max(pixel_array))
        if max_val == min_val:
            return np.zeros_like(pixel_array, dtype=np.uint8)
        scaled = (pixel_array - min_val) / (max_val - min_val) * 255.0
        return np.clip(scaled, 0, 255).astype(np.uint8)
    
    @staticmethod
    def normalize_pixel_array(pixel_array: np.ndarray) -> np.ndarray:
        """
        规范化像素数组到 0-255 范围
        
        Args:
            pixel_array: 原始像素数组
            
        Returns:
            规范化后的数组
        """
        # 处理多通道：保持 RGB/RGBA，不再强制降成单通道
        if pixel_array.ndim == 3 and pixel_array.shape[-1] in (3, 4):
            return ImageConverter._scale_to_uint8(pixel_array)

        # 单纯的多帧灰度数组不应该直接进入这里；如果进入则取第一帧兜底
        if len(pixel_array.shape) == 3:
            pixel_array = pixel_array[0]
        
        return ImageConverter._scale_to_uint8(pixel_array)
    
    @staticmethod
    def apply_window_level(
        pixel_array: np.ndarray,
        window_width: int = 400,
        window_center: int = 40
    ) -> np.ndarray:
        """
        应用窗口/窗位调整（用于 CT/MRI）
        
        Args:
            pixel_array: 原始像素数组
            window_width: 窗宽
            window_center: 窗位
            
        Returns:
            调整后的数组
        """
        below_min = pixel_array < (window_center - 0.5 - (window_width - 1) / 2)
        above_max = pixel_array > (window_center - 0.5 + (window_width - 1) / 2)
        between = np.logical_and(~below_min, ~above_max)
        
        result = np.zeros_like(pixel_array)
        result[below_min] = 0
        result[above_max] = 255
        result[between] = ((pixel_array[between] - (window_center - 0.5)) / 
                           (window_width - 1) + 0.5) * 255
        
        return result.astype(np.uint8)
    
    @staticmethod
    def pixel_array_to_image(
        pixel_array: np.ndarray,
        apply_windowing: bool = False
    ) -> Image.Image:
        """
        将像素数组转换为 PIL Image
        
        Args:
            pixel_array: 像素数组
            apply_windowing: 是否应用窗口/窗位
            
        Returns:
            PIL Image 对象
        """
        if pixel_array.ndim == 3 and pixel_array.shape[-1] in (3, 4):
            pixel_array = ImageConverter.normalize_pixel_array(pixel_array)
            mode = "RGBA" if pixel_array.shape[-1] == 4 else "RGB"
            image = Image.fromarray(pixel_array, mode=mode)
            return image

        # 应用窗口/窗位
        if apply_windowing:
            pixel_array = ImageConverter.apply_window_level(pixel_array)
        else:
            pixel_array = ImageConverter.normalize_pixel_array(pixel_array)

        # 创建图像
        image = Image.fromarray(pixel_array, mode="L")
        return image
    
    @staticmethod
    def save_as_png(
        pixel_array: np.ndarray,
        output_path: Optional[Path] = None,
        apply_windowing: bool = False
    ) -> Optional[bytes]:
        """
        保存为 PNG 格式
        
        Args:
            pixel_array: 像素数组
            output_path: 输出路径（可选）
            apply_windowing: 是否应用窗口/窗位
            
        Returns:
            PNG 字节数据或保存结果
        """
        image = ImageConverter.pixel_array_to_image(pixel_array, apply_windowing)
        
        if output_path:
            image.save(output_path, format="PNG")
            return None
        else:
            # 保存到字节流
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
    
    @staticmethod
    def save_as_jpeg(
        pixel_array: np.ndarray,
        output_path: Optional[Path] = None,
        quality: int = 90,
        apply_windowing: bool = False
    ) -> Optional[bytes]:
        """
        保存为 JPEG 格式
        
        Args:
            pixel_array: 像素数组
            output_path: 输出路径（可选）
            quality: JPEG 质量（1-100）
            apply_windowing: 是否应用窗口/窗位
            
        Returns:
            JPEG 字节数据或保存结果
        """
        image = ImageConverter.pixel_array_to_image(pixel_array, apply_windowing)
        
        if output_path:
            image.save(output_path, format="JPEG", quality=quality)
            return None
        else:
            # 保存到字节流
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality)
            return buffer.getvalue()
    
    @staticmethod
    def get_image_dimensions(pixel_array: np.ndarray) -> Tuple[int, int]:
        """
        获取图像尺寸
        
        Args:
            pixel_array: 像素数组
            
        Returns:
            (宽度, 高度) 元组
        """
        if len(pixel_array.shape) >= 2:
            return (pixel_array.shape[1], pixel_array.shape[0])
        return (0, 0)
