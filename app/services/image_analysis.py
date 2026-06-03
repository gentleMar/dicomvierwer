"""
OCR + OpenCV 图像分析服务
用于从当前展示的 DICOM 图像中提取文本和图像区域。
"""

from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import settings
from app.services.region_extraction import DEFAULT_MODE, get_region_extractor
from app.services.ocr_backends import get_ocr_backend, list_ocr_backends

try:
    import cv2
except Exception:  # pragma: no cover - 依赖缺失时由调用方处理
    cv2 = None


class ImageAnalysisService:
    """基于 OpenCV + OCR 的图像分析器。"""

    @staticmethod
    def analyze_png_bytes(
        image_bytes: bytes,
        ocr_lang: str = "chi_sim+eng",
        mode: str = DEFAULT_MODE,
        ocr_engine: str = "tesseract",
    ) -> Dict[str, Any]:
        if cv2 is None:
            raise RuntimeError("OpenCV 未安装，请先安装 opencv-python-headless")

        if not image_bytes:
            raise ValueError("图像数据为空")

        raw = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("无法解码图像数据")

        warnings: List[str] = []
        text = ImageAnalysisService._extract_text(bgr, ocr_lang=ocr_lang, warnings=warnings, ocr_engine=ocr_engine)
        diagnosis_opinions = ImageAnalysisService._extract_diagnosis_opinions(text)
        extractor = get_region_extractor(mode)
        regions = extractor.extract(bgr, warnings)

        return {
            "text": text,
            "diagnosis_opinions": diagnosis_opinions,
            "regions": regions,
            "warnings": warnings,
            "mode": extractor.mode,
        }

    @staticmethod
    def _configure_tesseract() -> None:
        # legacy helper kept for backward compatibility; actual OCR now delegated to backends
        try:
            from app.services import ocr_backends  # type: ignore
        except Exception:
            return

    @staticmethod
    def _ocr_candidates(gray: np.ndarray) -> List[np.ndarray]:
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        inverted = cv2.bitwise_not(otsu)
        return [gray, otsu, adaptive, inverted]

    @staticmethod
    def _extract_text(bgr: np.ndarray, ocr_lang: str, warnings: List[str], ocr_engine: str = "tesseract") -> str:
        """使用注册的 OCR 后端进行文本识别。后端未安装或失败时将返回空字符串并在 warnings 中写入原因。"""
        try:
            backend = get_ocr_backend(ocr_engine)
        except KeyError:
            warnings.append(f"未知的 OCR 引擎：{ocr_engine}")
            return ""
        except Exception as exc:
            warnings.append(f"加载 OCR 引擎失败：{exc}")
            return ""

        try:
            # 后端负责内部预处理
            text = backend.image_to_text(bgr, ocr_lang)
            return text or ""
        except ImportError as ie:
            warnings.append(str(ie))
            return ""
        except Exception as exc:  # pragma: no cover - 各后端运行时错误差异大
            warnings.append(f"OCR 运行失败：{exc}")
            return ""

    @staticmethod
    def _extract_diagnosis_opinions(text: str) -> List[str]:
        """从 OCR 文本中提取诊断意见，并按点拆分为便于外部读取的列表。"""
        if not text:
            return []

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        diagnosis_headers = [
            r"诊断意见",
            r"影像诊断",
            r"诊断结果",
            r"印象",
            r"结论",
            r"提示",
            r"意见",
        ]

        header_pattern = r"(?:" + "|".join(diagnosis_headers) + r")\s*[:：]?"
        header_match = re.search(header_pattern, normalized)

        if header_match:
            start = header_match.end()
            tail = normalized[start:]
        else:
            tail = normalized

        stop_markers = [r"检查所见", r"所见", r"病理", r"建议", r"备注", r"医生签名", r"审核", r"报告时间", r"录入者"]
        stop_pattern = r"(?:" + "|".join(stop_markers) + r")\s*[:：]"
        collected_lines: List[str] = []
        started = False
        for raw_line in tail.splitlines():
            line = raw_line.strip()
            if not line:
                if started:
                    break
                continue

            if re.search(stop_pattern, line) or "录入者" in line:
                break

            if re.match(r"^(?:\d+\s*[\).、．.]\s*|[-*•]\s*)", line):
                started = True
                collected_lines.append(line)
                continue

            if started:
                collected_lines.append(line)
                continue

            if header_match and line:
                started = True
                collected_lines.append(line)

        tail = "\n".join(collected_lines).strip()
        if not tail:
            return []

        parts = re.split(r"[\n；;]+", tail)
        opinions: List[str] = []

        for raw_part in parts:
            piece = raw_part.strip()
            if not piece:
                continue

            piece = re.sub(r"^(?:\d+\s*[\).、．.]\s*|[-*•]\s*)", "", piece)
            piece = piece.strip(" ：:，,。\t")
            if not piece:
                continue

            subpieces = [subpiece.strip() for subpiece in re.split(r"(?=(?:\d+\s*[\).、．.]\s*|[-*•]\s*))", piece) if subpiece.strip()]
            if len(subpieces) > 1:
                for subpiece in subpieces:
                    cleaned_piece = re.sub(r"^(?:\d+\s*[\).、．.]\s*|[-*•]\s*)", "", subpiece).strip(" ：:，,。\t")
                    if cleaned_piece:
                        opinions.append(cleaned_piece)
                continue

            opinions.append(piece)

        cleaned: List[str] = []
        seen = set()
        for item in opinions:
            item = re.sub(r"\s+", " ", item).strip()
            item = item.strip(" ：:，,。")
            if not item:
                continue
            if len(item) < 2:
                continue
            if item in seen:
                continue
            seen.add(item)
            cleaned.append(item)

        return cleaned

