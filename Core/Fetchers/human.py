"""
人类模式获取器
抢购专用,模拟真实人类行为:鼠标轨迹、随机延迟、误点修正等
"""
import random
import asyncio
from typing import Optional, Dict, Any, List, Tuple

from .browser import BrowserFetcher
from .base import FetcherMode


class HumanFetcher(BrowserFetcher):
    """人类模式获取器,抢购专用"""
    
    mode = FetcherMode.HUMAN
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        # 人类模式默认显示浏览器
        config.setdefault('headless', False)
        config.setdefault('anti_detect', True)

        super().__init__(config)

        # 行为参数
        self.mouse_speed = config.get('mouse_speed', 0.8)  # 鼠标移动速度 0-1
        self.click_delay_min = config.get('click_delay_min', 50)  # 点击前最小延迟 ms
        self.click_delay_max = config.get('click_delay_max', 200)  # 点击前最大延迟 ms
        self.type_delay_min = config.get('type_delay_min', 30)  # 输入间隔 ms
        self.type_delay_max = config.get('type_delay_max', 100)

        # 鼠标起点状态 - 首次移动用 viewport 中心,后续用上一次的位置
        # viewport 兜底为 1920x1080,真正初始化后用 self._page.viewport_size 更新
        self._last_mouse_pos: Tuple[int, int] = (
            config.get('viewport', {}).get('width', 1920) // 2,
            config.get('viewport', {}).get('height', 1080) // 2,
        )

        print("[HumanFetcher] Initialized in human mode")
        
    # ===== 贝塞尔曲线鼠标轨迹 =====
    
    def _bezier_curve(self, start: Tuple[int, int], end: Tuple[int, int], steps: int = 20) -> List[Tuple[int, int]]:
        """生成贝塞尔曲线轨迹"""
        x0, y0 = start
        x1, y1 = end
        
        # 随机控制点
        cx = x0 + (x1 - x0) * random.uniform(0.3, 0.7) + random.randint(-50, 50)
        cy = y0 + (y1 - y0) * random.uniform(0.3, 0.7) + random.randint(-30, 30)
        
        points = []
        for i in range(steps + 1):
            t = i / steps
            # 二次贝塞尔曲线
            x = int((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1)
            y = int((1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1)
            points.append((x, y))
            
        return points
        
    async def _human_mouse_move(self, target_x: int, target_y: int) -> None:
        """模拟人类鼠标移动"""
        if not self._page:
            return

        # 起点用上次记录的位置;首次默认 viewport 中心
        current_x, current_y = self._last_mouse_pos
        try:
            vp = self._page.viewport_size
            if vp and (current_x, current_y) == (960, 540):
                # 首次移动且实际视口存在,用真实中心点重置
                if vp['width'] != 1920 or vp['height'] != 1080:
                    current_x, current_y = vp['width'] // 2, vp['height'] // 2
                    self._last_mouse_pos = (current_x, current_y)
        except Exception:
            pass

        # 生成轨迹
        steps = max(5, int(30 * self.mouse_speed))
        points = self._bezier_curve((current_x, current_y), (target_x, target_y), steps)

        # 沿轨迹移动
        for x, y in points:
            await self._page.mouse.move(x, y)
            # 随机微小延迟
            await asyncio.sleep(random.uniform(0.005, 0.02) * (1 - self.mouse_speed))

        # 最后轻微抖动,模拟人手不稳定
        final_x, final_y = target_x, target_y
        for _ in range(random.randint(1, 3)):
            jitter_x = random.randint(-3, 3)
            jitter_y = random.randint(-3, 3)
            await self._page.mouse.move(target_x + jitter_x, target_y + jitter_y)
            await asyncio.sleep(random.uniform(0.01, 0.03))
        # 抖完后回到目标点
        await self._page.mouse.move(target_x, target_y)

        # 更新记录的位置
        self._last_mouse_pos = (final_x, final_y)
            
    async def _human_click_delay(self) -> None:
        """点击前随机延迟"""
        delay_ms = random.randint(self.click_delay_min, self.click_delay_max)
        await asyncio.sleep(delay_ms / 1000)
        
    async def _human_type_delay(self) -> None:
        """输入间隔随机延迟"""
        delay_ms = random.randint(self.type_delay_min, self.type_delay_max)
        await asyncio.sleep(delay_ms / 1000)
        
    # ===== 重写操作方法,加入人类行为 =====
    
    async def click(self, selector: str, **kwargs) -> None:
        """人类模式点击:移动鼠标 -> 随机延迟 -> 点击 -> 偶尔误点修正"""
        element = await self.find(selector)
        if element is None:
            from Core.Errors import ElementNotFoundError
            raise ElementNotFoundError(f"Element not found for click: {selector}")
            
        # 获取元素位置
        box = await element.bounding_box()
        if box:
            # 点击元素内随机位置,不是正中心
            target_x = int(box['x'] + random.uniform(0.2, 0.8) * box['width'])
            target_y = int(box['y'] + random.uniform(0.2, 0.8) * box['height'])
            
            # 移动鼠标
            await self._human_mouse_move(target_x, target_y)
            
            # 点击前延迟
            await self._human_click_delay()
            
            # 偶尔模拟误点(10% 概率点偏一点,然后修正)
            if random.random() < 0.1:
                wrong_x = target_x + random.randint(10, 30)
                wrong_y = target_y + random.randint(5, 20)
                await self._page.mouse.click(wrong_x, wrong_y)
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await self._human_mouse_move(target_x, target_y)
                await self._human_click_delay()
                
            # 正式点击
            await self._page.mouse.click(target_x, target_y)
        else:
            #  fallback 到普通点击
            await self._human_click_delay()
            await element.click(**kwargs)
            
    async def type(self, selector: str, text: str, **kwargs) -> None:
        """人类模式输入:逐字 + IME/composition + 节奏更真实。

        增强点(对比简单逐字 type):
            1. 中文场景:text 含 CJK 字符走 composition 路径,模拟输入法候选选词
            2. ASCII 场景: 偶尔打错+退格修正(2% 概率)
            3. 字符间延迟按类型分级(大写短/标点长)
            4. 长停顿 5%(思考)+ Tab 节奏 1.5%(多字段场景)
        """
        element = await self.find(selector)
        if element is None:
            from Core.Errors import ElementNotFoundError
            raise ElementNotFoundError(f"Element not found for type: {selector}")

        await element.click()
        await self._human_click_delay()

        is_cjk = any((
            "\u4e00" <= ch <= "\u9fff"
            or "\u3040" <= ch <= "\u309f"
            or "\u30a0" <= ch <= "\u30ff"
            or "\uac00" <= ch <= "\ud7af"
        ) for ch in text)

        if is_cjk and self._page is not None:
            await self._type_with_composition(text)
        else:
            await self._type_with_backspace_occasional(text)

    async def _type_with_composition(self, text: str) -> None:
        """中文 IME composition 事件链 + keyboard.insertText 注入最终文本。

        Playwright 没直接 composition API,我们用 evaluate 触发 DOM 上的
        compositionstart / compositionupdate / compositionend 事件链,
        然后用 keyboard.insertText 把最终文本塞入。
        """
        if not self._page:
            return
        # 1) compositionstart
        await self._page.evaluate("""() => {
            const el = document.activeElement;
            if (el && el.dispatchEvent) {
                el.dispatchEvent(new CompositionEvent('compositionstart', { data: '' }));
            }
        }""")
        # 2) 2-4 次 compositionupdate 模拟候选选词
        chunks = self._chunks_for_composition(text)
        for chunk in chunks:
            await self._page.evaluate(
                """(c) => {
                    const el = document.activeElement;
                    if (el && el.dispatchEvent) {
                        el.dispatchEvent(new CompositionEvent('compositionupdate', { data: c }));
                    }
                }""",
                chunk,
            )
            await asyncio.sleep(random.uniform(0.08, 0.30))
        # 3) compositionend
        await self._page.evaluate("""() => {
            const el = document.activeElement;
            if (el && el.dispatchEvent) {
                el.dispatchEvent(new CompositionEvent('compositionend', { data: '' }));
            }
        }""")
        # 4) insertText 真正塞文本
        await self._page.keyboard.insertText(text)
        # 5) 末尾短停
        await asyncio.sleep(random.uniform(0.05, 0.15))

    @staticmethod
    def _chunks_for_composition(text: str) -> list:
        """把一段中文分成 2-4 段模拟输入法候选选择。

        例: 8 字的"请按顺序点击张李王赵" 切成 ["请按顺序", "点击张", "李王赵"] 等。
        """
        n = len(text)
        if n <= 1:
            return [text]
        cuts = random.randint(2, min(4, n))
        chunks = []
        idx = 0
        for _ in range(cuts - 1):
            remain = n - idx
            step = max(1, remain // (cuts - len(chunks)))
            chunks.append(text[idx:idx + step])
            idx += step
        chunks.append(text[idx:])
        return chunks

    async def _type_with_backspace_occasional(self, text: str) -> None:
        """纯 ASCII 输入: 偶尔打错 + 退格修正, 节奏更细。

        节奏差异:
            - 大写字母 / 数字: 30-80ms(短停)
            - 标点 . , ! ?:  120-280ms(标点后停长些,真人也是)
            - 其他小写: 30-100ms(self.type_delay_min/max)
            - 长停顿 5%(200-800ms)
            - Tab 节奏 1.5%(30-100ms,模拟下一字段切换延迟)
        """
        if not self._page:
            return
        for i, char in enumerate(text):
            # 2% 概率打错+退格修正
            if random.random() < 0.02 and i > 0:
                wrong = chr(ord(char) ^ 0x01)
                try:
                    await self._page.keyboard.type(wrong)
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                    await self._page.keyboard.press("Backspace")
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                except Exception:
                    pass

            await self._page.keyboard.type(char)

            if char.isupper() or char.isdigit():
                await self._page.wait_for_timeout(random.randint(30, 80))
            elif char in (".", ",", "!", "?"):
                await self._page.wait_for_timeout(random.randint(120, 280))
            else:
                await self._human_type_delay()

            # 长停顿 5%
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.2, 0.8))
            # Tab 节奏 1.5%
            if random.random() < 0.015 and i < len(text) - 1:
                await asyncio.sleep(random.uniform(0.03, 0.10))

    async def preheat_element(self, selector: str) -> None:
        """预热元素:抢购前预先移动鼠标到目标位置,节省时间"""
        element = await self.find(selector)
        if element is None:
            return
            
        box = await element.bounding_box()
        if box:
            target_x = int(box['x'] + 0.5 * box['width'])
            target_y = int(box['y'] + 0.5 * box['height'])
            await self._human_mouse_move(target_x, target_y)
            print(f"[HumanFetcher] Preheated mouse to position ({target_x}, {target_y})")
