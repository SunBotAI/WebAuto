
# Demo 验证记录

## 目标
使用公开验证码 demo 页面验证「按顺序点汉字」技术方案的可行性。

## 测试目标
- 极验 demo：https://www.geetest.com/demo/
- 腾讯防水墙 demo：https://007.qq.com/

## 验证步骤
1. 访问 demo 页面
2. 观察验证码样式
3. 验证 OCR 识别
4. 验证浏览器自动化点击

## 验证结果

### 极验 Demo 页面
- 访问时间：2026-06-25
- 页面截图：`demo/geetest_demo_home.png`
- 验证码类型：
  - 文字点选
  - 滑块验证
  - 空间推理
  - 图标点选

### 技术可行性验证
待运行 demo 脚本后补充。

## 运行说明
```bash
# 安装依赖
pip install playwright
playwright install chromium

# 运行 demo
python scripts/demo_geetest.py
```
