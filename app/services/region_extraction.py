"""
图像区域提取接口与内置实现。

外部实现方只需要继承 `RegionExtractor` 并调用 `register_region_extractor()` 注册即可。
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import settings

try:
    import cv2
except Exception:  # pragma: no cover - 依赖缺失时由调用方处理
    cv2 = None


@dataclass(frozen=True)
class ExtractionPreset:
    """区域提取参数预设。"""

    white_threshold: int
    min_area_ratio: float
    max_aspect_ratio: float
    min_fill_ratio: float
    min_border_dark_ratio: float
    trim_white_threshold: int = 245


class RegionExtractor(ABC):
    """图像区域提取接口。"""

    mode: str = "base"
    label: str = "Base"
    description: str = "Abstract region extractor"

    @abstractmethod
    def extract(self, bgr: np.ndarray, warnings: List[str]) -> List[Dict[str, Any]]:
        """从图像中提取影像区域。"""

_REGISTRY: Dict[str, RegionExtractor] = {}

def register_region_extractor(extractor: RegionExtractor) -> None:
    """注册一个区域提取器。"""
    _REGISTRY[extractor.mode] = extractor


def get_region_extractor(mode: str) -> RegionExtractor:
    """按 mode 获取提取器，不存在时回退到默认实现。"""
    return _REGISTRY.get(mode) or _REGISTRY[DEFAULT_MODE]


def list_region_extractors() -> List[Dict[str, str]]:
    return [
        {"mode": extractor.mode, "label": extractor.label, "description": extractor.description}
        for extractor in _REGISTRY.values()
    ]



def _trim_border(img):

    gray = cv2.cvtColor(
        img,
        cv2.COLOR_BGR2GRAY,
    )

    bg = np.percentile(
        gray,
        99,
    )

    threshold = bg - 10

    mask = gray < threshold

    ys, xs = np.where(mask)

    if len(xs) == 0:
        return img, 0, 0

    top = ys.min()
    bottom = ys.max()

    left = xs.min()
    right = xs.max()

    margin = 2

    top = max(0, top - margin)
    left = max(0, left - margin)

    bottom = min(
        gray.shape[0],
        bottom + margin,
    )

    right = min(
        gray.shape[1],
        right + margin,
    )

    return (
        img[top:bottom, left:right],
        left,
        top,
    )

def _border_dark_ratio(gray: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    crop = gray[y:y + h, x:x + w]
    if crop.size == 0:
        return 0.0

    band = max(2, min(8, min(w, h) // 18))
    top = crop[:band, :]
    bottom = crop[-band:, :]
    left = crop[:, :band]
    right = crop[:, -band:]

    edge_pixels = np.concatenate([
        top.reshape(-1),
        bottom.reshape(-1),
        left.reshape(-1),
        right.reshape(-1),
    ])

    if edge_pixels.size == 0:
        return 0.0

    return float(np.mean(edge_pixels < 205))



class MedicalImageRegionExtractor(RegionExtractor):
    """
    医学影像矩形提取器

    特点：
    - 基于矩形检测而非连通域
    - 不容易把邻近文字一起裁进去
    - 自动透视裁剪
    - 自动去除白边
    """
    mode = "medical_rectangle"
    label = "医学影像矩形"
    description = "基于矩形轮廓检测的医学影像提取器"

    def extract(self, bgr: np.ndarray, warnings: List[str]) -> List[Dict[str, Any]]:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        page_h, page_w = gray.shape[:2]
        page_area = float(page_h * page_w)

        blur = cv2.GaussianBlur(gray, (3, 3), 0)

        edges = cv2.Canny(
            blur,
            threshold1=50,
            threshold2=150,
        )

        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (3, 3),
        )

        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=1,
        )

        contours_info = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        contours = (
            contours_info[0]
            if len(contours_info) == 2
            else contours_info[1]
        )

        candidates = []

        for contour in contours:

            area = cv2.contourArea(contour)

            if area < page_area * 0.01:
                continue

            peri = cv2.arcLength(contour, True)

            approx = cv2.approxPolyDP(
                contour,
                0.02 * peri,
                True,
            )

            if len(approx) != 4:
                continue

            if not cv2.isContourConvex(approx):
                continue

            x, y, w, h = cv2.boundingRect(approx)

            aspect = w / max(h, 1)

            if aspect < 0.4:
                continue

            if aspect > 5.5:
                continue

            border_score = self._border_score(
                gray,
                approx,
            )

            if border_score < 0.15:
                continue

            texture_score = self._texture_score(
                gray,
                x,
                y,
                w,
                h,
            )

            if texture_score < 8:
                continue

            score = (
                area / page_area * 40
                + border_score * 40
                + min(texture_score, 30)
            )

            candidates.append(
                {
                    "approx": approx,
                    "rect": (x, y, w, h),
                    "score": score,
                    "area": area,
                }
            )

        candidates.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        selected = []

        for cand in candidates:
            keep = True

            for exist in selected:
                if self._iou(
                    cand["rect"],
                    exist["rect"],
                ) > 0.4:
                    keep = False
                    break

            if keep:
                selected.append(cand)

        max_regions = int(
            getattr(
                settings,
                "analysis_max_regions",
                20,
            )
            or 20
        )

        regions = []

        for idx, cand in enumerate(selected[:max_regions]):

            warped = self._perspective_crop(
                bgr,
                cand["approx"],
            )

            if warped.size == 0:
                continue

            warped, dx, dy = _trim_border(warped)

            ok, encoded = cv2.imencode(
                ".png",
                warped,
            )

            if not ok:
                continue

            x, y, w, h = cand["rect"]

            regions.append(
                {
                    "index": idx,
                    "x": int(x),
                    "y": int(y),
                    "width": int(w),
                    "height": int(h),
                    "area_ratio": round(
                        cand["area"] / page_area,
                        6,
                    ),
                    "image_base64": base64.b64encode(
                        encoded.tobytes()
                    ).decode("ascii"),
                }
            )

        return regions

    @staticmethod
    def _texture_score(
        gray: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> float:

        crop = gray[y:y+h, x:x+w]

        if crop.size == 0:
            return 0.0

        return float(np.std(crop))

    @staticmethod
    def _border_score(
        gray: np.ndarray,
        approx: np.ndarray,
    ) -> float:

        x, y, w, h = cv2.boundingRect(approx)

        crop = gray[y:y+h, x:x+w]

        if crop.size == 0:
            return 0.0

        band = max(
            2,
            min(
                10,
                min(w, h) // 25,
            ),
        )

        top = crop[:band, :]
        bottom = crop[-band:, :]
        left = crop[:, :band]
        right = crop[:, -band:]

        edge_pixels = np.concatenate(
            [
                top.ravel(),
                bottom.ravel(),
                left.ravel(),
                right.ravel(),
            ]
        )

        return float(
            np.mean(edge_pixels < 220)
        )

    @staticmethod
    def _iou(
        r1,
        r2,
    ):

        x1, y1, w1, h1 = r1
        x2, y2, w2, h2 = r2

        xa = max(x1, x2)
        ya = max(y1, y2)

        xb = min(x1 + w1, x2 + w2)
        yb = min(y1 + h1, y2 + h2)

        inter_w = max(0, xb - xa)
        inter_h = max(0, yb - ya)

        inter = inter_w * inter_h

        union = (
            w1 * h1
            + w2 * h2
            - inter
        )

        return inter / union if union > 0 else 0

    @staticmethod
    def _order_points(
        pts: np.ndarray,
    ):

        pts = pts.reshape(4, 2).astype(np.float32)

        rect = np.zeros(
            (4, 2),
            dtype=np.float32,
        )

        s = pts.sum(axis=1)

        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        diff = np.diff(
            pts,
            axis=1,
        )

        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]

        return rect

    @classmethod
    def _perspective_crop(
        cls,
        image,
        approx,
    ):

        rect = cls._order_points(approx)

        tl, tr, br, bl = rect

        widthA = np.linalg.norm(br - bl)
        widthB = np.linalg.norm(tr - tl)

        maxW = int(max(widthA, widthB))

        heightA = np.linalg.norm(tr - br)
        heightB = np.linalg.norm(tl - bl)

        maxH = int(max(heightA, heightB))

        if maxW < 10 or maxH < 10:
            return np.empty((0, 0, 3), dtype=np.uint8)

        dst = np.array(
            [
                [0, 0],
                [maxW - 1, 0],
                [maxW - 1, maxH - 1],
                [0, maxH - 1],
            ],
            dtype=np.float32,
        )

        M = cv2.getPerspectiveTransform(
            rect,
            dst,
        )

        return cv2.warpPerspective(
            image,
            M,
            (maxW, maxH),
        )

DEFAULT_MODE = "medical_rectangle"

register_region_extractor(MedicalImageRegionExtractor())