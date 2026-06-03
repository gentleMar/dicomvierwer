# 图像矩形区域提取接口说明书

本文档说明当前程序中用于“从图像中识别影像矩形区域”的接口约定。外部实现方只需要按本文档实现一个提取器，并注册到程序中即可被前端的“解析方式”下拉框调用。

## 1. 目标

本接口的目标不是做 OCR，而是从已经渲染出来的图像中提取矩形影像区域，并导出这些区域的图像内容。

要求：
- 输入是一张已渲染的图像（OpenCV `BGR ndarray`）
- 输出是若干个矩形区域
- 每个区域必须返回图像内容，不需要返回 OCR 文本
- 支持通过 `mode` 切换不同提取方式

## 2. 接口位置

接口定义位于：
- `app/services/region_extraction.py`

核心接口：
- `RegionExtractor`

注册函数：
- `register_region_extractor(extractor)`
- `get_region_extractor(mode)`
- `list_region_extractors()`

## 3. 接口定义

### 3.1 `RegionExtractor`

外部实现方需要继承该抽象接口：

```python
class RegionExtractor(ABC):
    mode: str
    label: str
    description: str

    @abstractmethod
    def extract(self, bgr: np.ndarray, warnings: List[str]) -> List[Dict[str, Any]]:
        ...
```

### 3.2 方法说明

#### `extract(bgr, warnings)`

参数：
- `bgr`：OpenCV 读取后的整图，类型为 `np.ndarray`
- `warnings`：告警列表，提取失败或发生退化时可往里追加字符串

返回：
- `List[Dict[str, Any]]`

每个字典至少应包含以下字段：
- `index`：区域序号，从 0 开始
- `x`：区域左上角 X 坐标
- `y`：区域左上角 Y 坐标
- `width`：区域宽度
- `height`：区域高度
- `area_ratio`：区域面积占整图面积比例
- `image_base64`：区域图像的 PNG base64 内容

说明：
- 不需要返回 OCR 文本
- 建议返回裁剪后的最终有效区域，而不是包含整页白边的大框
- 若发现异常，可将原因写入 `warnings`

## 4. 模式切换

前端会通过 `mode` 参数调用解析接口：

```http
GET /api/dicom/analyze?path=...&frame=0&mode=opencv_border_relaxed
```

当前页面右侧的下拉框会从接口加载可用模式：

```http
GET /api/dicom/analyze/modes
```

返回示例：

```json
[
  {
    "mode": "opencv_border_relaxed",
    "label": "边缘黑矩形（宽松）",
    "description": "适合白底报告里的常规黑边矩形影像块，偏向召回。"
  }
]
```

## 5. 外部实现接入方式

外部只需要：

1. 新建一个 `RegionExtractor` 子类
2. 实现 `mode / label / description / extract()`
3. 在启动阶段调用 `register_region_extractor(your_extractor)`
4. 前端下拉框会自动显示该 `mode`

示例：

```python
from app.services.region_extraction import RegionExtractor, register_region_extractor

class MyExtractor(RegionExtractor):
    mode = "my_custom_mode"
    label = "我的自定义方式"
    description = "由外部系统实现的提取方式"

    def extract(self, bgr, warnings):
        return []

register_region_extractor(MyExtractor())
```

## 6. 约束

- 不要在区域提取接口里做 OCR
- 不要修改前端调用约定，保持 `mode` 参数可切换
- 只返回图像区域，不返回报告背景白边
- 如果外部 mode 不存在，程序会回退到默认 mode

## 7. 默认实现

当前程序内置了一个实现。

## 8. 备注

如果后续需要更换为其他算法（例如模板匹配、深度学习检测、版式分析），只要实现同一个接口并注册新的 `mode` 即可，无需修改前端调用入口。
