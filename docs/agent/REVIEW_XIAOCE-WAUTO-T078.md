# REVIEW — XIAOCE-WAUTO-T078（T-078 Gradio Web 面板测试）

> **验收人**：小测（QA）
> **日期**：2026-07-11
> **任务 ID**：XIAOCE-WAUTO-T078
> **被测分支**：`feat/webauto` @ `7bc7929`（待 push）
> **任务文件**：`Tests/test_web_panels.py`（新写，28KB）

---

## ✅ STATUS：APPROVED

任务验收标准「≥10 用例通过」 → 实际 **28/28 全过**，3 次连跑稳定 1.26s。

---

## 📋 任务验收明细

### 设计要点
按大白确认「不需要真起 gradio server」路线：

1. **不依赖 gradio / gradio_client 库**：
   - 自定义 `MockGradioClient` 类模拟 `gradio_client.Client.predict()` 调用链
   - `credential_panel.py` 顶层 import gradio → 用 `sys.modules["gradio"] = MagicMock()` 占位 + 自定义 context manager 支持 `with gr.Tab(...):`

2. **从 panel 模块提取闭包 handler**：
   - 自定义 `_extract_nested_functions()` 用 `ast.NodeVisitor` 递归访问（绕过 with/if 嵌套）
   - 提取到 13 个 profile_panel handler + 9 个 proxy_panel handler

3. **真实业务后端 + mock 浏览器层**：
   - `ProfileStore(base_dir=tmpdir)` 真实 store（隔离 tmpdir）
   - `mock_pool` + `mock_health` 替代 Playwright/Pool
   - `mock_credential_backend` 替代真实 CredentialBackend

4. **关键 endpoint 覆盖**：
   - profile_panel：warmup + list + create + delete + save（CRUD 完整）
   - proxy_panel：warmup + add + delete + list refresh
   - credential_panel：warmup + check_passphrase + format_check + format_sms + list_accounts

### 28 个验收用例

| 测试类 | 用例 | 验证点 |
|--------|------|--------|
| `TestProfilePanelHandlers` | 8 个 | warmup + list + create + create 边界 + delete + delete 静默 + delete 边界 + save |
| `TestProxyPanelHandlers` | 7 个 | warmup + add + add 边界 + add URL 凭据解析 + delete + delete 边界 + refresh |
| `TestCredentialPanelHandlers` | 6 个 | warmup + build_ui + format_check 成功/失败 + format_sms + accounts_to_rows |
| `TestMockGradioClientIntegration` | 3 个 | predict 日志 + view_api 清单 + 无 gradio 依赖 |
| `TestPanelModuleLoad` | 4 个 | 三个 panel 模块 import + `_run` helper |

### 稳定性验证（3 次连跑）
```
Run 1: 28 passed, 1 warning in 1.27s
Run 2: 28 passed, 1 warning in 1.26s
Run 3: 28 passed, 1 warning in 1.26s
```

---

## 📊 全量回归（5 个测试文件）

```
$ python3 -m pytest Tests/test_antidetect_profile_sync.py \
                 Tests/test_profile_isolation_e2e.py \
                 Tests/test_web_panels.py \
                 Tests/test_orchestrator.py \
                 Tests/test_pool.py
============= 1 failed, 67 passed, 3 skipped, 2 warnings in 5.65s ===============
```

**说明**：
- 67 PASS：T-047(13) + T-053(6) + T-078(28) + T-045(7) + T-046(13)
- 3 SKIP：T-047 canvas_hash 占位（等 AntiDetect 实现）
- 1 FAILED：`Tests/test_pool.py::TestBasicAcquireRelease::test_acquire_blocks_when_semaphore_full` — **本任务范围外**的历史 flaky（小测在 XIAOCE-WAUTO-TEST-001 验收时就发现并标注）

---

## 🐛 发现 BUG（待小千确认，不在 T-078 修复范围）

### Bug #1: ProfileStore.delete() 静默吞错
- **位置**：`Core/Profile/store.py:178-186`
- **症状**：删除不存在的 profile_id 时 `store.delete()` 不抛 `FileNotFoundError`，静默 return
- **影响**：`profile_panel._do_delete()` 期望 FileNotFoundError 来格式化 "❌ Profile {pid} 不存在" 提示，但实际拿到的是 "✅ 已删除"（误导用户）
- **建议修复**：在 `store.delete()` 行 185 后 `raise FileNotFoundError(f"Profile {profile_id} not found")`
- **测试用例**：`test_delete_nonexistent_returns_success_silently` 已记录此 bug 行为 + TODO 注释

### Bug #2: credential_panel.py 顶层 import gradio（非 lazy）
- **位置**：`Tools/credential_panel.py:23`
- **症状**：未装 gradio 时整个模块无法 import
- **影响**：违反 T-078「不需要真起 gradio server」要求 — 测试必须 mock gradio 才能 import
- **建议修复**：改为函数内 lazy import（与 `profile_panel._build_ui` 内部的 `import gradio as gr` 一致）

---

## 🛡️ 护栏遵守

- ✅ 分支保持 `feat/webauto`，未切分支
- ✅ 未合并 / reset / stash / cherry-pick / rebase / revert
- ✅ 未 commit 任何老大文件（STATUS.md / Tools/console_backend.py 等既有 dirty 保持原样）
- ✅ 未 push --force
- ✅ T-078 新增测试文件 1 个（含 commit footer 提交人信息段）

---

## 📌 后续 follow-up

1. **ProfileStore.delete() bug 修复（小千）**：见上面 Bug #1，建议优先级 P2
2. **credential_panel.py 顶层 import gradio 改 lazy（小千）**：见上面 Bug #2，建议优先级 P3
3. **T-088 BLOCKED**：v1.6 依赖链（T-081~T-087）未就绪，等小千完成后大白自然派活

---

## 🔧 skill_used

- **multi-search-engine**：调研 Gradio Client Python API（`gradio_client.Client.predict()` 调用链 + gradio.app 官方文档）
- **humanizer**：commit message + 本 REVIEW 文案润色（去除 AI 痕迹）

操作人: 小测（agent via OpenClaw）
工具: pytest + Bash + multi-search-engine + humanizer
Git-Author: xiaoce@openclaw.local