"""
OCR 后端适配器集合。
提供可注册的 OCRBackend 接口与内置的 Tesseract / PaddleOCR (CPU) 实现。
如果宿主环境未安装某个依赖，相关后端会在初始化时抛出 ImportError，调用方应当处理并回退。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional
import numpy as np

_BACKENDS: Dict[str, "OCRBackend"] = {}


def _configure_paddle_runtime():
    """尽量关闭 Paddle 3.x 的 PIR 执行路径，降低 CPU 推理兼容性问题。"""
    os.environ.setdefault("FLAGS_enable_pir_api", "false")
    os.environ.setdefault("FLAGS_enable_pir_in_executor", "false")


class OCRBackend:
    mode: str = "base"

    def image_to_text(self, bgr: "np.ndarray", ocr_lang: str) -> str:
        """将 BGR 图像（OpenCV 格式）识别为文本。返回识别到的字符串（可能为空）。"""
        raise NotImplementedError()


def register_ocr_backend(backend: OCRBackend):
    _BACKENDS[backend.mode] = backend


def list_ocr_backends() -> List[Dict[str, str]]:
    return [{"mode": k, "label": getattr(v, "label", k)} for k, v in _BACKENDS.items()]


def get_ocr_backend(mode: Optional[str]) -> OCRBackend:
    if not mode:
        mode = "tesseract"
    backend = _BACKENDS.get(mode)
    if backend is None:
        raise KeyError(f"Unknown OCR backend: {mode}")
    return backend


class TesseractBackend(OCRBackend):
    mode = "tesseract"
    label = "Tesseract"

    def __init__(self, tesseract_cmd: Optional[str] = None):
        try:
            import pytesseract  # type: ignore
        except Exception as exc:  # pragma: no cover - 环境依赖
            raise ImportError("pytesseract 未安装") from exc
        self._pytesseract = pytesseract
        if tesseract_cmd:
            try:
                self._pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)
            except Exception:
                pass

    def image_to_text(self, bgr: np.ndarray, ocr_lang: str) -> str:
        import cv2

        pytesseract = self._pytesseract
        # 尝试多种二值化/预处理策略以提高召回
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        try:
            _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        except Exception:
            otsu = blurred

        try:
            adaptive = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
            )
        except Exception:
            adaptive = blurred

        inverted = cv2.bitwise_not(otsu)
        candidates = [gray, otsu, adaptive, inverted]

        langs = [ocr_lang, "eng"] if ocr_lang else ["eng"]
        config = "--oem 3 --psm 6"

        for lang in langs:
            for cand in candidates:
                try:
                    txt = pytesseract.image_to_string(cand, lang=lang, config=config)
                    txt = txt.strip()
                    if txt:
                        return txt
                except Exception:
                    continue

        return ""


class PaddleOCRBackend(OCRBackend):
    mode = "paddleocr_cpu"
    label = "PaddleOCR (CPU)"

    def __init__(self, use_gpu: bool = False, lang: str = "ch"):
        self._use_gpu = bool(use_gpu)
        self._lang = lang
        # 延迟初始化模型（可能较大）
        self._PaddleOCR = None
        self._instance = None

    def _init(self):
        if self._instance is None:
            _configure_paddle_runtime()
            if self._PaddleOCR is None:
                try:
                    from paddleocr import PaddleOCR  # type: ignore
                except Exception as exc:  # pragma: no cover - 环境依赖
                    raise ImportError("paddleocr 未安装") from exc
                self._PaddleOCR = PaddleOCR

            # PaddleOCR 3.x 不再接受 use_gpu 参数；CPU 模式下直接使用默认设备即可。
            init_kwargs = {
                "device": "cpu",
                "use_angle_cls": False,
                "lang": self._lang,
                "enable_hpi": False,
                "enable_mkldnn": False,
                "enable_cinn": False,
            }

            try:
                self._instance = self._PaddleOCR(**init_kwargs)
            except TypeError:
                # 兼容不同版本的参数命名差异，去掉额外参数后重试。
                self._instance = self._PaddleOCR()

    def image_to_text(self, bgr: np.ndarray, ocr_lang: str) -> str:
        # PaddleOCR 推荐使用 numpy.ndarray（RGB uint8）或图像路径字符串。
        import cv2

        self._init()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        np_img = np.asarray(rgb, dtype=np.uint8)

        # 直接传 numpy 数组；若失败让上层捕获并记录警告。
        ocr_result = self._instance.ocr(np_img)

        # 部分版本会返回包含 result() 的包装对象，统一展开
        if hasattr(ocr_result, "result") and callable(getattr(ocr_result, "result")):
            try:
                ocr_result = ocr_result.result()
            except Exception:
                pass

        def collect_texts(value):
            texts = []
            if value is None:
                return texts
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    texts.append(stripped)
                return texts
            if isinstance(value, dict):
                for key in ("rec_texts", "texts", "text", "rec_text", "ocr_text"):
                    if key in value:
                        texts.extend(collect_texts(value[key]))
                return texts
            if isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, dict):
                        texts.extend(collect_texts(item))
                        continue
                    if isinstance(item, (list, tuple)):
                        if len(item) >= 2 and isinstance(item[1], (str, int, float)):
                            texts.extend(collect_texts(item[1]))
                            continue
                        if len(item) >= 2 and isinstance(item[1], (list, tuple)) and item[1]:
                            texts.extend(collect_texts(item[1][0]))
                            continue
                    texts.extend(collect_texts(item))
            return texts

        parts = collect_texts(ocr_result)

        joined = "\n".join([p.strip() for p in parts if p and str(p).strip()])
        return joined


# 注册内置后端（延迟创建实例以便配置生效）
def _register_defaults():
    try:
        # 尝试使用系统配置的 tesseract 命令前缀
        from app.config import settings
        tcmd = getattr(settings, "tesseract_cmd", None)
        try:
            register_ocr_backend(TesseractBackend(tesseract_cmd=tcmd))
        except Exception:
            # 若 pytesseract 缺失，则不阻塞注册其它后端
            pass
    except Exception:
        pass

    try:
        register_ocr_backend(PaddleOCRBackend(use_gpu=False))
    except Exception:
        # paddle 未安装时忽略
        pass


_register_defaults()
