# QUALITY_STATUS

> 状态：NEEDS_VERIFICATION / 最后更新：2026-08-27

## 最近一次有效测试证据

命令：`pytest Tests -q`

结果：**235 passed, 2 failed, 4 skipped**（约 91.68s）

- 4 skipped：Chrome E2E，`WEBAUTO_CHROME_EXECUTABLE` 不可用。
- 2 failed：
  - `Tests/v3/test_dashboard_conversations.py` — Dashboard 出现 conversation 控件断言失败；
  - `Tests/v3/test_vertical_dashboard.py` — Dashboard 出现 vertical 控件断言失败。

范围口径：

- `Tests/v3` 子集：232 passed / 2 failed / 4 skipped；
- `Tests` 全量（含 `test_v3_package_baseline.py`）：235 passed / 2 failed / 4 skipped。

## 结论

- 非 Chrome 测试接近全绿，但**不能据此宣称 v3.3 发布**：两个失败属于 B1 删除方向的守卫，B4 重写。
- Chrome E2E 尚无证据（缺可执行文件）。
- 历史 M0—M8 报告已归档，不得用于证明当前版本。
