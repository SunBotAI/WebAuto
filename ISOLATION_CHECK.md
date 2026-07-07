
# 隔离清单检查

检查时间：2026-06-25

## 检查项

- [x] 代码目录只在 `~/.openclaw/workspaces/xiaoqian/tools/webauto/`
- [x] 独立 `.venv/` 在 `tools/webauto/` 内部
- [x] 智谱账号/cookie 在 `tools/webauto/.env`（已 gitignore）
- [x] `tools/webauto/.gitignore` 至少含 `.venv/` 和 `.env`
- [x] `git status` 显示**没有** ShopAuto `back/` 或 `front/` 文件改动
- [x] 没有 kill / restart ShopAuto uvicorn / celery / next-server 进程
- [x] worklog / TASKS / git commit 都在小千 namespace，**不混 ShopAuto 分支**

## 验证命令

```bash
# 检查 ShopAuto 目录状态
cd /mnt/f/Project/ShopAuto/back && git status
cd /mnt/f/Project/ShopAuto/front && git status

# 检查 webauto 目录
ls -la ~/.openclaw/workspaces/xiaoqian/tools/webauto/
```
