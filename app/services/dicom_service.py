"""
DICOM 服务模块
处理 DICOM 文件的读取和处理
"""

from pathlib import Path
from typing import Optional, Dict, Any, Union, List
import io
import threading
import time
from collections import OrderedDict

import pydicom
from pydicom.errors import InvalidDicomError

from app.config import settings
from app.models.schemas import DICOMMetadata
from app.utils.image_utils import ImageConverter


class _RenderedFrameCache:
    def __init__(self):
        self._store = OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0

    def _now(self) -> float:
        return time.time()

    def _limits(self):
        max_bytes = getattr(settings, "render_cache_max_bytes", None)
        max_items = getattr(settings, "render_cache_max_items", None)
        ttl = getattr(settings, "render_cache_ttl_seconds", None)
        return max_bytes, max_items, ttl

    def _evict_expired(self):
        _, _, ttl = self._limits()
        if not ttl:
            return
        now = self._now()
        expired = [key for key, (_, _, created) in self._store.items() if now - created > ttl]
        for key in expired:
            _, size, _ = self._store.pop(key, (None, 0, 0))
            self._bytes -= size

    def get(self, key: str):
        with self._lock:
            self._evict_expired()
            if key not in self._store:
                raise KeyError(key)
            data, size, created = self._store.pop(key)
            self._store[key] = (data, size, created)
            return data

    def set(self, key: str, data: bytes):
        with self._lock:
            self._evict_expired()
            if key in self._store:
                _, old_size, _ = self._store.pop(key)
                self._bytes -= old_size
            self._store[key] = (data, len(data), self._now())
            self._bytes += len(data)
            self._enforce_limits()

    def _enforce_limits(self):
        max_bytes, max_items, _ = self._limits()
        while self._store and ((max_bytes and self._bytes > max_bytes) or (max_items and len(self._store) > max_items)):
            _, (data, size, _) = self._store.popitem(last=False)
            self._bytes -= size

    def clear(self):
        with self._lock:
            self._store.clear()
            self._bytes = 0

    def stats(self):
        max_bytes, max_items, ttl = self._limits()
        return {
            "items": len(self._store),
            "bytes": self._bytes,
            "max_items": max_items,
            "max_bytes": max_bytes,
            "ttl_seconds": ttl,
        }


_rendered_frame_cache = _RenderedFrameCache()


class _DatasetCache:
    def __init__(self):
        self._store = OrderedDict()
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.time()

    def _limits(self):
        max_items = getattr(settings, "dataset_cache_max_items", None)
        ttl = getattr(settings, "dataset_cache_ttl_seconds", None)
        return max_items, ttl

    def _evict_expired(self):
        _, ttl = self._limits()
        if not ttl:
            return
        now = self._now()
        expired = [key for key, (_, created) in self._store.items() if now - created > ttl]
        for key in expired:
            self._store.pop(key, None)

    def get(self, key: str):
        with self._lock:
            self._evict_expired()
            if key not in self._store:
                raise KeyError(key)
            dataset, created = self._store.pop(key)
            self._store[key] = (dataset, created)
            return dataset

    def set(self, key: str, dataset):
        with self._lock:
            self._evict_expired()
            if key in self._store:
                self._store.pop(key)
            self._store[key] = (dataset, self._now())
            self._enforce_limits()

    def _enforce_limits(self):
        max_items, _ = self._limits()
        while self._store and (max_items and len(self._store) > max_items):
            self._store.popitem(last=False)

    def clear(self):
        with self._lock:
            self._store.clear()

    def stats(self):
        max_items, ttl = self._limits()
        return {
            "items": len(self._store),
            "max_items": max_items,
            "ttl_seconds": ttl,
        }


_dataset_cache = _DatasetCache()


class DICOMService:
    """DICOM 服务"""
    
    # DICOM 标签映射
    METADATA_TAGS = {
        "PatientName": ("0x00100010", "patient_name"),
        "PatientID": ("0x00100020", "patient_id"),
        "StudyDate": ("0x00080020", "study_date"),
        "Modality": ("0x00080060", "modality"),
        "SeriesDescription": ("0x0008103e", "series_description"),
        "InstanceNumber": ("0x00200013", "instance_number"),
        "Rows": ("0x00280010", "rows"),
        "Columns": ("0x00280011", "columns"),
        "BitsAllocated": ("0x00280100", "bits_allocated"),
        "BitsStored": ("0x00280101", "bits_stored"),
        "HighBit": ("0x00280102", "high_bit"),
        "PixelRepresentation": ("0x00280103", "pixel_representation"),
        "NumberOfFrames": ("0x00280008", "number_of_frames"),
        "PhotometricInterpretation": ("0x00280004", "photometric_interpretation"),
    }

    @staticmethod
    def _cache_key(dicom_source: Union[Path, bytes], frame: int, format_name: str, quality: Optional[int] = None) -> str:
        if isinstance(dicom_source, Path):
            try:
                stat = dicom_source.stat()
                source_sig = f"path:{dicom_source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
            except Exception:
                source_sig = f"path:{dicom_source.resolve()}"
        else:
            source_sig = f"bytes:{id(dicom_source)}:{len(dicom_source)}"
        quality_sig = "" if quality is None else f":q{quality}"
        return f"{source_sig}:f{frame}:fmt{format_name}{quality_sig}"

    @staticmethod
    def _source_signature(dicom_source: Union[Path, bytes]) -> str:
        if isinstance(dicom_source, Path):
            try:
                stat = dicom_source.stat()
                return f"path:{dicom_source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
            except Exception:
                return f"path:{dicom_source.resolve()}"
        return f"bytes:{hash(dicom_source)}:{len(dicom_source)}"

    @staticmethod
    def _dataset_cache_key(dicom_source: Union[Path, bytes], stop_before_pixels: bool) -> str:
        return f"{DICOMService._source_signature(dicom_source)}:sbp{int(stop_before_pixels)}"
    
    @staticmethod
    def _open_dataset(dicom_source: Union[Path, bytes], stop_before_pixels: bool = True):
        """Return pydicom Dataset from Path or bytes."""
        try:
            cache_key = DICOMService._dataset_cache_key(dicom_source, stop_before_pixels)
            try:
                return _dataset_cache.get(cache_key)
            except KeyError:
                pass

            if isinstance(dicom_source, (bytes, bytearray)):
                dataset = pydicom.dcmread(io.BytesIO(dicom_source), stop_before_pixels=stop_before_pixels)
            else:
                dataset = pydicom.dcmread(dicom_source, stop_before_pixels=stop_before_pixels)
            _dataset_cache.set(cache_key, dataset)
            return dataset
        except Exception as e:
            raise

    @staticmethod
    def _format_code_meaning(item) -> Optional[str]:
        try:
            if hasattr(item, "ConceptNameCodeSequence") and item.ConceptNameCodeSequence:
                code_item = item.ConceptNameCodeSequence[0]
                meaning = getattr(code_item, "CodeMeaning", None)
                if meaning:
                    return str(meaning)
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_sr_lines(dataset, depth: int = 0) -> List[str]:
        lines: List[str] = []
        content_sequence = getattr(dataset, "ContentSequence", None)
        if not content_sequence:
            return lines

        indent = "  " * depth
        for item in content_sequence:
            try:
                label = DICOMService._format_code_meaning(item) or str(getattr(item, "ValueType", "ITEM"))
                value_type = str(getattr(item, "ValueType", "")).upper()

                if value_type == "CONTAINER":
                    lines.append(f"{indent}{label}:")
                    lines.extend(DICOMService._extract_sr_lines(item, depth + 1))
                    continue

                value = None
                for field_name in (
                    "TextValue",
                    "NumericValue",
                    "PersonName",
                    "UID",
                    "DateTime",
                    "Date",
                    "Time",
                    "CodeMeaning",
                ):
                    field_value = getattr(item, field_name, None)
                    if field_value not in (None, ""):
                        value = str(field_value)
                        break

                if value is None:
                    if hasattr(item, "ReferencedSOPSequence"):
                        value = f"Referenced items: {len(item.ReferencedSOPSequence)}"
                    else:
                        value = ""

                if value:
                    lines.append(f"{indent}{label}: {value}")
                else:
                    lines.append(f"{indent}{label}")

                if hasattr(item, "ContentSequence") and item.ContentSequence:
                    lines.extend(DICOMService._extract_sr_lines(item, depth + 1))
            except Exception:
                continue

        return lines

    @staticmethod
    def extract_structured_report(dicom_source: Union[Path, bytes]) -> Dict[str, Any]:
        """提取 SR 结构化报告文本。

        返回适合直接展示的标题与正文。
        """
        try:
            dcm = DICOMService._open_dataset(dicom_source, stop_before_pixels=True)
        except (InvalidDicomError, Exception) as e:
            raise ValueError(f"Invalid DICOM file: {str(e)}")

        modality = str(getattr(dcm, "Modality", "")).upper() or None
        title = None
        try:
            title = str(getattr(dcm, "SeriesDescription", None) or getattr(dcm, "DocumentTitle", None) or "结构化报告")
        except Exception:
            title = "结构化报告"

        lines: List[str] = []
        if hasattr(dcm, "ContentSequence") and dcm.ContentSequence:
            lines = DICOMService._extract_sr_lines(dcm, 0)

        if not lines:
            # 回退到常见文本字段
            for field_name in ("TextValue", "DocumentTitle", "SeriesDescription"):
                value = getattr(dcm, field_name, None)
                if value not in (None, ""):
                    lines = [str(value)]
                    break

        return {
            "modality": modality,
            "title": title,
            "text": "\n".join(lines).strip(),
        }


    def read_metadata(dicom_source: Union[Path, bytes]) -> Optional[DICOMMetadata]:
        """
        读取 DICOM 文件元数据
        
        Args:
            dicom_path: DICOM 文件路径
            
        Returns:
            DICOM 元数据
            
        Raises:
            ValueError: 文件不是有效的 DICOM 文件
        """
        try:
            # 仅读取元数据，不读取像素数据
            dcm = DICOMService._open_dataset(dicom_source, stop_before_pixels=True)
        except (InvalidDicomError, Exception) as e:
            raise ValueError(f"Invalid DICOM file: {str(e)}")
        
        # 提取元数据
        metadata = DICOMMetadata()
        
        try:
            metadata.patient_name = str(dcm.PatientName) if hasattr(dcm, "PatientName") else None
        except Exception:
            pass
        
        try:
            metadata.patient_id = str(dcm.PatientID) if hasattr(dcm, "PatientID") else None
        except Exception:
            pass
        
        try:
            metadata.study_date = str(dcm.StudyDate) if hasattr(dcm, "StudyDate") else None
        except Exception:
            pass
        
        try:
            metadata.modality = str(dcm.Modality) if hasattr(dcm, "Modality") else None
        except Exception:
            pass
        
        try:
            metadata.series_description = str(dcm.SeriesDescription) if hasattr(dcm, "SeriesDescription") else None
        except Exception:
            pass
        
        try:
            metadata.instance_number = int(dcm.InstanceNumber) if hasattr(dcm, "InstanceNumber") else None
        except Exception:
            pass
        
        try:
            metadata.rows = int(dcm.Rows) if hasattr(dcm, "Rows") else None
        except Exception:
            pass
        
        try:
            metadata.columns = int(dcm.Columns) if hasattr(dcm, "Columns") else None
        except Exception:
            pass
        
        try:
            metadata.bits_allocated = int(dcm.BitsAllocated) if hasattr(dcm, "BitsAllocated") else None
        except Exception:
            pass
        
        try:
            metadata.bits_stored = int(dcm.BitsStored) if hasattr(dcm, "BitsStored") else None
        except Exception:
            pass
        
        try:
            metadata.high_bit = int(dcm.HighBit) if hasattr(dcm, "HighBit") else None
        except Exception:
            pass
        
        try:
            metadata.pixel_representation = int(dcm.PixelRepresentation) if hasattr(dcm, "PixelRepresentation") else None
        except Exception:
            pass
        
        try:
            metadata.number_of_frames = int(dcm.NumberOfFrames) if hasattr(dcm, "NumberOfFrames") else None
        except Exception:
            metadata.number_of_frames = 1
        
        try:
            metadata.photometric_interpretation = str(dcm.PhotometricInterpretation) if hasattr(dcm, "PhotometricInterpretation") else None
        except Exception:
            pass
        
        return metadata
    
    @staticmethod
    def get_pixel_array(dicom_source: Union[Path, bytes], frame: int = 0) -> Optional[Any]:
        """
        获取 DICOM 文件的像素数据
        
        Args:
            dicom_path: DICOM 文件路径
            frame: 帧索引（用于多帧图像）
            
        Returns:
            像素数组
            
        Raises:
            ValueError: 文件不是有效的 DICOM 文件或无法获取像素数据
        """
        try:
            dcm = DICOMService._open_dataset(dicom_source, stop_before_pixels=False)
        except (InvalidDicomError, Exception) as e:
            raise ValueError(f"Invalid DICOM file: {str(e)}")

        if not (
            hasattr(dcm, "PixelData")
            or hasattr(dcm, "FloatPixelData")
            or hasattr(dcm, "DoubleFloatPixelData")
        ):
            modality = str(getattr(dcm, "Modality", "UNKNOWN"))
            raise ValueError(
                f"DICOM file has no pixel data and cannot be rendered as an image (modality: {modality})"
            )
        
        try:
            pixel_array = dcm.pixel_array

            samples_per_pixel = int(getattr(dcm, "SamplesPerPixel", 1) or 1)
            photometric = str(getattr(dcm, "PhotometricInterpretation", "")).upper()
            is_color = samples_per_pixel > 1 or photometric in {
                "RGB",
                "YBR_FULL",
                "YBR_FULL_422",
                "YBR_PARTIAL_420",
                "YBR_RCT",
                "YBR_ICT",
            }

            # 只在真正的多帧时按 frame 切片，不把 RGB 单帧图像误当成多帧。
            if is_color:
                if pixel_array.ndim == 4:
                    if frame >= pixel_array.shape[0]:
                        raise ValueError(f"Frame index {frame} out of range")
                    pixel_array = pixel_array[frame]
            else:
                if pixel_array.ndim == 3:
                    if frame >= pixel_array.shape[0]:
                        raise ValueError(f"Frame index {frame} out of range")
                    pixel_array = pixel_array[frame]

            pixel_array = ImageConverter.convert_photometric_array(pixel_array, photometric)
            
            return pixel_array
        except Exception as e:
            raise ValueError(f"Failed to get pixel array: {str(e)}")
    
    @staticmethod
    def render_to_png(dicom_source: Union[Path, bytes], frame: int = 0) -> bytes:
        """
        将 DICOM 文件渲染为 PNG
        
        Args:
            dicom_path: DICOM 文件路径
            frame: 帧索引
            
        Returns:
            PNG 字节数据
        """
        cache_key = DICOMService._cache_key(dicom_source, frame, "png")
        try:
            return _rendered_frame_cache.get(cache_key)
        except KeyError:
            pass

        pixel_array = DICOMService.get_pixel_array(dicom_source, frame)
        image_data = ImageConverter.save_as_png(pixel_array)
        _rendered_frame_cache.set(cache_key, image_data)
        return image_data
    
    @staticmethod
    def render_to_jpeg(dicom_source: Union[Path, bytes], frame: int = 0, quality: int = 90) -> bytes:
        """
        将 DICOM 文件渲染为 JPEG
        
        Args:
            dicom_path: DICOM 文件路径
            frame: 帧索引
            quality: JPEG 质量
            
        Returns:
            JPEG 字节数据
        """
        cache_key = DICOMService._cache_key(dicom_source, frame, "jpeg", quality)
        try:
            return _rendered_frame_cache.get(cache_key)
        except KeyError:
            pass

        pixel_array = DICOMService.get_pixel_array(dicom_source, frame)
        image_data = ImageConverter.save_as_jpeg(pixel_array, quality=quality)
        _rendered_frame_cache.set(cache_key, image_data)
        return image_data

    @staticmethod
    def rendered_cache_stats() -> Dict[str, Any]:
        stats = _rendered_frame_cache.stats()
        stats["dataset_cache"] = _dataset_cache.stats()
        return stats

    @staticmethod
    def clear_rendered_cache() -> None:
        _rendered_frame_cache.clear()
        _dataset_cache.clear()

    @staticmethod
    def prefetch_rendered_frames(
        dicom_source: Union[Path, bytes],
        frame: int,
        total_frames: Optional[int] = None,
        format_name: str = "png",
        quality: int = 90,
        radius: int = 2,
    ) -> None:
        if total_frames is None:
            try:
                metadata = DICOMService.read_metadata(dicom_source)
                total_frames = metadata.number_of_frames or 1
            except Exception:
                total_frames = 1

        if total_frames <= 1:
            return

        for offset in range(1, radius + 1):
            for next_frame in (frame + offset, frame - offset):
                if next_frame < 0 or next_frame >= total_frames:
                    continue
                try:
                    if format_name == "jpeg":
                        DICOMService.render_to_jpeg(dicom_source, next_frame, quality=quality)
                    else:
                        DICOMService.render_to_png(dicom_source, next_frame)
                except Exception:
                    continue
