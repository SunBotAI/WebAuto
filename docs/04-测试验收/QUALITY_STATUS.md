# QUALITY_STATUS

> 状态：B0-03 BASELINE_FROZEN / 最后更新：2026-08-27

## B0-03 测试基线（已冻结）

**冻结 commit**：`e86d124` (tag `v3.3-baseline-20260827`)

### 命令与结果

```
$ .venv/bin/python -m pytest Tests -q --no-header -p no:cacheprovider
... 235 passed, 2 failed, 4 skipped in 78.60s (0:01:18)
```

### 范围口径

| 范围 | passed | failed | skipped |
|---|---:|---:|---:|
| `Tests/v3` 子集 | 232 | 2 | 4 |
| `Tests` 全量（含 `test_v3_package_baseline.py`） | 235 | 2 | 4 |

### 4 skipped

均为 Chrome E2E：`WEBAUTO_CHROME_EXECUTABLE` 在本机不可用。**B4-03 必须用真实 Chrome 跑出至少 1 条 Managed E2E + 1 条 CDP 冒烟。**

### 2 failed（已冻结为 B0 基线，不要求 B0 修）

| 测试 | 含义 | 期望修复阶段 |
|---|---|---|
| `Tests/v3/test_dashboard_conversations.py` | 断言 Dashboard 不应出现 conversation 控件（Butler/Conversation 删除方向守卫） | **B4-02** 改写为新基线 |
| `Tests/v3/test_vertical_dashboard.py` | 断言 Dashboard 不应出现 vertical 控件（Vertical 删除方向守卫） | **B4-02** 改写为新基线 |

### B1 起门禁

按 [最终方案 §17.4](../01-项目方案/WebAuto-最终方案.md)，**B1 起每阶段结束非 Chrome 测试必须全绿**。B1-04「无旁路」测试新增；B2-02/B2-03 可能临时翻转个别守卫，需在 B1—B3 完成后再统一在 B4-02 收尾。

## 结论

- **B0-03 基线已冻结**（含 2 个已知失败 + 4 个 Chrome skipped）；不能据此宣称 v3.3 已通过发布门禁。
- Chrome E2E 尚无证据，必须由 B4-03 提供。
- 历史 M0—M8 / Browser-Agent 报告已删除，不得用于证明当前版本。
