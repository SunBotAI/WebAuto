# MCP pool - 工具清单与 Schema 文档

> **MCP Server**: `webauto-pool`  
> **协议版本**: MCP 1.0  
> **后端模块**: `Core/Profile/pool.py` + `Core/Profile/orchestrator.py`  
> **状态**: T-084 完成

---

## 概览

`pool` 处理 Profile 池的运行时管理，支持并发借还、策略切换和状态控制。

**核心概念**：
- **Profile 池**：多个 Profile 共享，并发任务通过 `acquire/release` 借还
- **AcquireStrategy**：选择策略（round_robin / random / sticky_by_tag / least_used / health_based）
- **并发控制**：通过 `max_concurrent` 信号量限制同时借出的 Profile 数量
- **脏页追踪**：Pool 内部批量异步写盘，避免频繁 IO 阻塞事件循环

**配置文件**: `~/.cache/webauto/profiles/pool.yaml`

---

## 工具清单（8 个）

| # | 工具名 | 说明 |
|---|--------|------|
| 1 | `pool_acquire` | 从池中借出一个可用 Profile |
| 2 | `pool_release` | 归还 Profile 到池中 |
| 3 | `pool_status` | 获取池状态快照 |
| 4 | `pool_ban` | 将 Profile 标记为 banned（永久） |
| 5 | `pool_cooldown` | 将 Profile 设为 cooldown（临时） |
| 6 | `pool_set_strategy` | 切换池选择策略 |
| 7 | `pool_set_max_concurrent` | 修改最大并发数 |
| 8 | `pool_uncooldown_profile` | 提前解除 Profile 的 cooldown |

---

## AcquireStrategy 枚举

| 策略 | 说明 |
|------|------|
| `round_robin` | 轮询选择(公平) |
| `random` | 随机选择 |
| `sticky_by_tag` | 同一 tag 始终返回同一个 Profile |
| `least_used` | 选择 `last_used` 最旧的(复用率最高) |
| `health_based` | 优先选 READY,其次选 cooldown 已到期的 |

---

## Schema 定义

### tool: pool_acquire

从池中借出一个可用的 Profile。

**Input Schema**:
```json
{
  "tag": "string | null",      // 用于 sticky_by_tag 策略,同一 tag 总是返回同一 Profile
  "timeout": "float | null"    // 借不到时的超时秒数(默认 30.0)
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "acquired": true,
  "strategy": "string",
  "in_use_count": "integer"
}
```

**错误响应**:
```json
{
  "error": "No available profile for tag=xxx after 30.0s",
  "acquired": false
}
```

**说明**:
- 借出的 Profile `status` 会被设为 `RUNNING`,不可被其他任务借走
- `in_use_count` 为当前池中在借 Profile 总数

---

### tool: pool_release

归还 Profile 到池中。

**Input Schema**:
```json
{
  "profile_id": "string (required)",
  "cooldown": "float (optional, default=0)" // 归还后冷却秒数,防风控
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "released": true,
  "cooldown_seconds": "float",
  "new_status": "ready | cooldown"
}
```

**说明**: `cooldown=0`（默认）立即变 `READY`；`cooldown>0` 变 `COOLDOWN`，cooldown 期间不可借。若 Profile 已是 `BANNED` 或 `ARCHIVED`，不覆盖状态，只刷脏页。

---

### tool: pool_status

获取池的运行时状态快照。

**Input Schema**:
```json
{
  // 无需参数
}
```

**Output Schema**:
```json
{
  "total": "integer",
  "ready": "integer",
  "running": "integer",
  "cooldown": "integer",
  "banned": "integer",
  "archived": "integer",
  "in_use_ids": ["string"],
  "strategy": "round_robin | random | sticky_by_tag | least_used | health_based",
  "max_concurrent": "integer"
}
```

**示例**:
```json
{
  "total": 10,
  "ready": 6,
  "running": 3,
  "cooldown": 1,
  "banned": 0,
  "archived": 0,
  "in_use_ids": ["profile-002", "profile-005", "profile-008"],
  "strategy": "least_used",
  "max_concurrent": 5
}
```

---

### tool: pool_ban

将 Profile 永久标记为 banned(不可再借)。

**Input Schema**:
```json
{
  "profile_id": "string (required)"
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "banned": true,
  "previous_status": "string"
}
```

**说明**: BANNED 是终态，不可逆。想恢复只能删掉重创建。

---

### tool: pool_cooldown

将 Profile 设为临时 cooldown 状态。

**Input Schema**:
```json
{
  "profile_id": "string (required)",
  "duration": "float (required)" // cooldown 持续秒数
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "cooldown_until": "ISO8601",
  "new_status": "cooldown"
}
```

**说明**: cooldown 期间 Profile 不可借，到期后自动恢复 `READY`。

---

### tool: pool_set_strategy

切换池的 Profile 选择策略。

**Input Schema**:
```json
{
  "strategy": "round_robin | random | sticky_by_tag | least_used | health_based (required)"
}
```

**Output Schema**:
```json
{
  "previous_strategy": "string",
  "new_strategy": "string",
  "persisted": "boolean" // 是否持久化到 pool.yaml
}
```

**说明**: 策略变更立即生效，同时写入 `pool.yaml` 持久化。

---

### tool: pool_set_max_concurrent

修改池的最大并发 Profile 数量。

**Input Schema**:
```json
{
  "max_concurrent": "integer (required)" // >= 1
}
```

**Output Schema**:
```json
{
  "previous_max": "integer",
  "new_max": "integer",
  "current_in_use": "integer",
  "persisted": "boolean"
}
```

**约束**: `max_concurrent >= 1`,否则报错。

**说明**: 实时生效（重建 Semaphore），同时写入 `pool.yaml`。若当前 `in_use_count > new_max`，已在借的 Profile 不受影响，但会阻止新借出直到并发数降下来。

---

### tool: pool_uncooldown_profile

提前解除 Profile 的 cooldown 状态。

**Input Schema**:
```json
{
  "profile_id": "string (required)"
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "uncooled": true,
  "previous_status": "cooldown",
  "new_status": "ready"
}
```

**错误响应**:
```json
{
  "error": "Profile is not in cooldown",
  "profile_id": "string"
}
```

**说明**: 人工确认 Profile 已恢复后，提前放回可用池用这个。

---

## 脏页追踪机制

Pool 内部维护 `_dirty` 字典记录被修改但未刷盘的 Profile,通过后台 flush loop 定期批量写盘:

- **flush_interval**: 默认 5 秒
- **触发时机**: `acquire()` 前自动 flush、`release()` 后标记脏页
- **手动触发**: `pool_flush`(立即刷盘)
- **停止**: `pool_stop`(停止 flush loop 并刷最后的脏页)

> **注意**: MCP 层可通过 `pool_flush` / `pool_stop` 工具(可选扩展)手动控制刷盘时机。

---

## 生命周期图

```
acquire() → Profile (RUNNING) → release(cooldown=0) → Profile (READY)
                                     └→ release(cooldown>0) → Profile (COOLDOWN) → [到期] → Profile (READY)
                                     └→ ban() → Profile (BANNED) [终态]
                                     └→ archive() → Profile (ARCHIVED) [终态]
```

---

## MCP 集成示例

### Claude Desktop

```json
{
  "mcpServers": {
    "webauto-pool": {
      "command": "python",
      "args": [
        "-m", "webauto.mcp.pool_server"
      ],
      "env": {
        "WEBAUTO_BASE_DIR": "~/.cache/webauto"
      }
    }
  }
}
```

### Cursor

```json
{
  "mcpServers": {
    "webauto-pool": {
      "command": "uvicorn",
      "args": [
        "webauto.mcp.pool_server:app",
        "--host", "127.0.0.1",
        "--port", "8082"
      ],
      "env": {
        "WEBAUTO_BASE_DIR": "~/.cache/webauto"
      }
    }
  }
}
```

---

*文档版本: v1.0 | 生成时间: 2026-07-14 | Task: T-084*
