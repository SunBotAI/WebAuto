"""
验证码识别核心模块
基于 ddddocr / PaddleOCR 的中文点选验证码识别
✅ 自动检测依赖,缺啥装啥,不用提前手动安装
"""
import io
import time
import base64
import subprocess
import sys
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class CaptchaType(Enum):
    """验证码类型"""
    CHINESE_CLICK = "chinese_click"  # 中文点选
    SLIDE = "slide"                    # 滑块
    ROTATE = "rotate"                  # 旋转
    PUZZLE = "puzzle"                  # 拼图
    TEXT = "text"                      # 普通文字


@dataclass
class CaptchaResult:
    """验证码识别结果"""
    success: bool
    captcha_type: CaptchaType
    points: List[Tuple[int, int]]      # 点击坐标序列
    target_text: str                 # 目标文字
    raw_result: Dict[str, Any]       # 原始识别结果
    confidence: float = 0.0
    solve_time_ms: float = 0.0


@dataclass
class OCRBox:
    """OCR 识别框"""
    text: str
    confidence: float
    box: List[Tuple[int, int]]         # 四个角坐标
    center: Tuple[int, int]              # 中心点坐标


class OCREngineType(Enum):
    """OCR 引擎类型"""
    DDDDOCR = "ddddocr"  # 轻量,中文识别效果好,安装快
    PADDLEOCR = "paddleocr"  # 百度 PaddleOCR,功能全,体积大
    AUTO = "auto"  # 自动选择可用的


def _install_package(package: str) -> bool:
    """自动 pip 安装包"""
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", package,
            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
            "--break-system-packages"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False


class OCREngine:
    """OCR 引擎封装 - 自动检测并安装依赖
    优先用轻量 ddddocr,PaddleOCR 备选
    """
    
    def __init__(
        self,
        engine_type: OCREngineType = OCREngineType.AUTO,
        use_gpu: bool = False,
        auto_install: bool = True
    ):
        self.engine_type = engine_type
        self.use_gpu = use_gpu
        self.auto_install = auto_install
        self._engine = None
        self._det = None
        self._det_func = None
        self._initialized = False
        
    def _try_import_ddddocr(self) -> bool:
        """尝试导入 ddddocr"""
        try:
            import ddddocr
            self._det = ddddocr.DdddOcr(show_ad=False, beta=True)
            # ddddocr.detection(image_bytes) -> List[[box, text, confidence], ...]
            self._det_func = self._det.detection
            self.engine_type = OCREngineType.DDDDOCR
            return True
        except ImportError:
            return False
        except Exception as e:
            print(f"[OCREngine] ddddocr 初始化失败: {e}")
            return False
    
    def _try_import_paddleocr(self) -> bool:
        """尝试导入 PaddleOCR"""
        try:
            from paddleocr import PaddleOCR
            self._det = PaddleOCR(
                use_angle_cls=False,
                lang="ch",
                use_gpu=self.use_gpu,
                show_log=False
            )
            self._det_func = self._det.ocr
            self.engine_type = OCREngineType.PADDLEOCR
            return True
        except ImportError:
            return False
    
    async def init(self) -> None:
        """异步初始化,自动安装缺失的依赖"""
        if self._initialized:
            return
            
        # 先尝试导入 ddddocr(轻量优先)
        if self.engine_type in (OCREngineType.AUTO, OCREngineType.DDDDOCR):
            if self._try_import_ddddocr():
                self._initialized = True
                print(f"[OCREngine] 使用 ddddocr 引擎")
                return
        
        # ddddocr 不行试 PaddleOCR
        if self.engine_type in (OCREngineType.AUTO, OCREngineType.PADDLEOCR):
            if self._try_import_paddleocr():
                self._initialized = True
                print(f"[OCREngine] 使用 PaddleOCR 引擎")
                return
        
        # 都没装,尝试自动安装
        if self.auto_install:
            print("[OCREngine] 未检测到 OCR 引擎,正在自动安装 ddddocr...")
            if _install_package("ddddocr"):
                if self._try_import_ddddocr():
                    self._initialized = True
                    print(f"[OCREngine] ddddocr 自动安装成功")
                    return
            
            # ddddocr 安装失败试 PaddleOCR
            print("[OCREngine] ddddocr 安装失败,尝试 PaddleOCR...")
            if _install_package("paddlepaddle") and _install_package("paddleocr"):
                if self._try_import_paddleocr():
                    self._initialized = True
                    print(f"[OCREngine] PaddleOCR 自动安装成功")
                    return
        
        raise RuntimeError(
            "所有 OCR 引擎初始化失败!\n"
            "请手动安装: pip install ddddocr -i https://pypi.tuna.tsinghua.edu.cn/simple"
        )
    
    async def detect_text_boxes(
        self,
        image_bytes: bytes,
        target_chars: Optional[List[str]] = None
    ) -> List[OCRBox]:
        """
        检测图片中的文字框
        
        Args:
            image_bytes: 图片二进制
            target_chars: 目标文字提示,用于排序优化
            
        Returns:
            OCRBox 列表
        """
        start = time.time()
        await self.init()

        boxes = []

        if self.engine_type == OCREngineType.DDDDOCR:
            result = self._det_func(image_bytes)
            boxes = self._parse_ddddocr_result(result)
        elif self.engine_type == OCREngineType.PADDLEOCR:
            result = self._det_func(image_bytes, cls=False)
            boxes = self._parse_paddleocr_result(result)

        elapsed = (time.time() - start) * 1000
        print(f"[OCR] 检测到 {len(boxes)} 个文字框,耗时 {elapsed:.1f}ms (engine={self.engine_type.value})")

        if target_chars and boxes:
            boxes = self._sort_by_target_chars(boxes, target_chars)

        return boxes
        
    def _parse_ddddocr_result(self, result) -> List[OCRBox]:
        """
        解析 ddddocr 结果

        ddddocr.detection(image_bytes) 返回格式:
            [
                [box_points, text, confidence],
                ...
            ]
        其中 box_points 是 4 个 (x, y) 顶点的列表(按顺时针).
        部分老版本格式为 [[box, ...]] 后跟 dict/text/位置参数,这里对两种结构都做兜底.
        """
        boxes: List[OCRBox] = []
        if not result:
            return boxes

        for item in result:
            try:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue

                # --- 提取 box ---
                box_field = item[0]
                box_points: list = []

                # box 可能是 [[x,y], [x,y], [x,y], [x,y]] 或 (x1,y1,x2,y2,...) 等
                if isinstance(box_field, (list, tuple)) and len(box_field) >= 4:
                    first = box_field[0]
                    # 形态 A: 4 个顶点
                    if isinstance(first, (list, tuple)) and len(first) == 2:
                        for pt in box_field[:4]:
                            if isinstance(pt, (list, tuple)) and len(pt) == 2:
                                box_points.append((int(pt[0]), int(pt[1])))
                    # 形态 B: 8 个连续数字 [x1,y1,x2,y2,x3,y3,x4,y4]
                    elif isinstance(first, (int, float)):
                        flat = [float(v) for v in box_field[:8]]
                        box_points = [
                            (int(flat[0]), int(flat[1])),
                            (int(flat[2]), int(flat[3])),
                            (int(flat[4]), int(flat[5])),
                            (int(flat[6]), int(flat[7])),
                        ]

                if len(box_points) != 4:
                    continue

                # --- 提取 text & confidence ---
                text_field = item[1]
                conf_field = item[2] if len(item) > 2 else 1.0

                if isinstance(text_field, (list, tuple)):
                    # 形态: [text, confidence] 内嵌
                    if len(text_field) >= 2 and isinstance(text_field[1], (int, float)):
                        text = str(text_field[0])
                        confidence = float(text_field[1])
                    else:
                        text = " ".join(str(t) for t in text_field)
                        confidence = float(conf_field) if isinstance(conf_field, (int, float)) else 1.0
                else:
                    text = str(text_field)
                    confidence = float(conf_field) if isinstance(conf_field, (int, float)) else 1.0

                xs = [p[0] for p in box_points]
                ys = [p[1] for p in box_points]
                center = (int(sum(xs) / 4), int(sum(ys) / 4))

                boxes.append(OCRBox(
                    text=text,
                    confidence=confidence,
                    box=[(x, y) for (x, y) in box_points],
                    center=center,
                ))
            except Exception:
                # 单条解析失败不影响整体
                continue

        return boxes
        
    def _parse_paddleocr_result(self, result) -> List[OCRBox]:
        """解析 PaddleOCR 结果"""
        boxes = []
        if not result or not result[0]:
            return boxes
            
        for line in result[0]:
            box_coords = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]
            text, confidence = line[1][0], line[1][1]
            
            xs = [p[0] for p in box_coords]
            ys = [p[1] for p in box_coords]
            center_x = int(sum(xs) / 4)
            center_y = int(sum(ys) / 4)
            
            boxes.append(OCRBox(
                text=text,
                confidence=confidence,
                box=[(int(p[0]), int(p[1])) for p in box_coords],
                center=(center_x, center_y)
            ))
        return boxes
        
    def _sort_by_target_chars(self, boxes: List[OCRBox], target_chars: List[str]) -> List[OCRBox]:
        """按目标文字顺序排序"""
        result = []
        used = set()
        
        for target_char in target_chars:
            best_match = None
            best_score = -1
            for i, box in enumerate(boxes):
                if i in used:
                    continue
                if target_char in box.text:
                    score = box.confidence
                else:
                    score = 0
                if score > best_score:
                    best_score = score
                    best_match = i
            if best_match is not None:
                result.append(boxes[best_match])
                used.add(best_match)
                
        for i, box in enumerate(boxes):
            if i not in used:
                result.append(box)
        return result


class CaptchaSolver:
    """验证码求解器 - 主入口"""

    def __init__(
        self,
        ocr_engine: Optional[OCREngine] = None,
        auto_install_ocr: bool = True
    ):
        self.ocr = ocr_engine or OCREngine(auto_install=auto_install_ocr)
        self._initialized = False
        
    async def init(self) -> None:
        """初始化(会自动安装 OCR 依赖)"""
        if not self._initialized:
            await self.ocr.init()
            self._initialized = True
            
    async def solve_chinese_click(
        self,
        image_bytes: bytes,
        target_chars: str,
        image_size: Optional[Tuple[int, int]] = None
    ) -> CaptchaResult:
        """
        求解中文点选验证码
        
        Args:
            image_bytes: 验证码图片二进制
            target_chars: 需要点击的目标文字(如"你好世界")
            image_size: 图片实际尺寸(用于缩放时坐标校正)
            
        Returns:
            CaptchaResult 包含点击坐标序列
        """
        start = time.time()
        await self.init()
        
        target_list = list(target_chars.strip())
        if not target_list:
            return CaptchaResult(
                success=False,
                captcha_type=CaptchaType.CHINESE_CLICK,
                points=[],
                target_text=target_chars,
                raw_result={},
                solve_time_ms=(time.time() - start) * 1000
            )
            
        boxes = await self.ocr.detect_text_boxes(image_bytes, target_list)
        
        points = []
        matched_chars = []
        confidences = []
        
        for target in target_list:
            for box in boxes:
                if target in box.text and box.center not in [(p[0], p[1]) for p in points]:
                    points.append(box.center)
                    matched_chars.append(box.text)
                    confidences.append(box.confidence)
                    break
                    
        success = len(points) == len(target_list)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        result = CaptchaResult(
            success=success,
            captcha_type=CaptchaType.CHINESE_CLICK,
            points=points,
            target_text=target_chars,
            raw_result={
                "matched": matched_chars,
                "all_boxes": [(b.text, b.center, b.confidence) for b in boxes]
            },
            confidence=avg_confidence,
            solve_time_ms=(time.time() - start) * 1000
        )
        
        print(
            f"[Captcha] {'✅' if success else '❌'} "
            f"target={target_chars}, matched={len(points)}/{len(target_list)}, "
            f"points={points}, time={result.solve_time_ms:.1f}ms"
        )
        
        return result
        
    async def solve_from_page(
        self,
        page,  # Playwright Page 对象
        captcha_selector: str = 'iframe[src*="captcha"], iframe[src*="geetest"]',
        target_selector: str = '[class*="prompt"], [class*="text"], .verify-header'
    ) -> CaptchaResult:
        """
        直接从 Playwright 页面自动求解验证码
        
        Args:
            page: Playwright Page 对象
            captcha_selector: 验证码 iframe 选择器
            target_selector: 目标文字选择器
            
        Returns:
            CaptchaResult
        """
        await self.init()
        
        iframe = await page.wait_for_selector(captcha_selector, timeout=5000)
        if not iframe:
            raise RuntimeError("未找到验证码 iframe")
            
        frame = await iframe.content_frame()
        if not frame:
            raise RuntimeError("无法访问验证码 iframe")
            
        target_elem = await frame.wait_for_selector(target_selector, timeout=3000)
        target_text = (await target_elem.inner_text()) if target_elem else ""
        target_chars = "".join([c for c in target_text if "\u4e00" <= c <= "\u9fff"])
        
        img_elem = await frame.wait_for_selector(
            'img, canvas, [style*="background-image"]',
            timeout=3000
        )
        if not img_elem:
            raise RuntimeError("未找到验证码图片")
            
        screenshot = await img_elem.screenshot(type="png")
        
        result = await self.solve_chinese_click(screenshot, target_chars)
        
        if result.success:
            box = await img_elem.bounding_box()
            if box:
                from PIL import Image
                img = Image.open(io.BytesIO(screenshot))
                scale_x = box["width"] / img.width
                scale_y = box["height"] / img.height
                result.points = [
                    (int(x * scale_x + box["x"]), int(y * scale_y + box["y"]))
                    for (x, y) in result.points
                ]
        return result
        
    async def click_points(
        self,
        page,
        result: CaptchaResult,
        delay_range: Tuple[float, float] = (0.3, 0.8)
    ) -> None:
        """
        按识别结果在页面上点击"""
        if not result.success:
            raise RuntimeError("验证码识别失败,无法点击")
        import asyncio
        import numpy as np
        for i, (x, y) in enumerate(result.points):
            await page.mouse.move(x, y, steps=np.random.randint(5, 15))
            await asyncio.sleep(np.random.uniform(0.05, 0.15))
            await page.mouse.click(x, y)
            if i < len(result.points) - 1:
                delay = np.random.uniform(*delay_range)
                await asyncio.sleep(delay)
        print(f"[Captcha] 已点击 {len(result.points)} 个点")


async def install_ocr_deps(engine="auto"):
    """
    便捷函数:一键安装 OCR 依赖
    Args:
        engine: "ddddocr" / "paddleocr" / "auto"(默认先装 ddddocr)
    """
    if engine == "auto":
        engine = "ddddocr"
    print(f"[CaptchaSolver] 正在安装 {engine}...")
    if _install_package(engine):
        print(f"[CaptchaSolver] {engine} 安装成功!")
        return True
    print(f"[CaptchaSolver] {engine} 安装失败")
    return False
