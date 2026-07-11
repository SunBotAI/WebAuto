# MCP proxy_backend — 工具清单与 Schema 文档

> **MCP Server**: `webauto-proxy`  
> **协议版本**: MCP 1.0  
> **后端模块**: `Core/ProxyPool/proxy.py` + `Core/ProxyPool/health.py`  
> **状态**: T-083 完成

---

## 概览

`proxy_backend` 处理全局代理池的增删改查，带健康追踪和批量操作。

**全局代理池** vs Profile 内嵌 proxy_pool：
- 全局：所有 Profile 共享一份代理，跨 Profile 复用率更高（推荐）
- 内嵌：`Profile.network.proxy_pool`，Profile 独立维护

**健康数据目录**: `~/.cache/webauto/proxies/proxy_health.json`

---

## 工具清单（8 个）

| # | 工具名 | 说明 |
|---|--------|------|
| 1 | `proxy_list` | 列出所有代理 |
| 2 | `proxy_get` | 获取单个代理详情（含健康状态） |
| 3 | `proxy_create` | 添加新代理 |
| 4 | `proxy_update` | 更新代理配置 |
| 5 | `proxy_delete` | 删除代理 |
| 6 | `proxy_health_check` | 对代理发起健康检查 |
| 7 | `proxy_bulk_import` | 批量导入代理（支持 TXT/CSV） |
| 8 | `proxy_reset_health` | 重置代理健康状态 |

---

## Schema 定义

### tool: proxy_list

列出所有代理条目（不含健康详情，如需详情用 `proxy_get`）。

**Input Schema**:
```json
{
  // 无需参数
}
```

**Output Schema**:
```json
{
  "proxies": [
    {
      "id": "string",
      "url": "string",
      "proxy_type": "http | https | socks5",
      "region": "string | null",
      "tags": ["string"],
      "enabled": "boolean",
      "notes": "string"
    }
  ],
  "total": "integer"
}
```

**示例**:
```json
{
  "proxies": [
    {
      "id": "proxy-001",
      "url": "http://user:pass@103.72.145.67:3000",
      "proxy_type": "http",
      "region": "US",
      "tags": ["residential", "datacenter"],
      "enabled": true,
      "notes": "US 住宅代理"
    }
  ],
  "total": 1
}
```

---

### tool: proxy_get

获取单个代理的完整信息，包含健康状态记录。

**Input Schema**:
```json
{
  "proxy_id": "string (required)"
}
```

**Output Schema**:
```json
{
  "proxy": {
    "id": "string",
    "url": "string",
    "proxy_type": "string",
    "username": "string | null",
    "password": "string | null",
    "region": "string | null",
    "tags": ["string"],
    "enabled": "boolean",
    "notes": "string"
  },
  "health": {
    "proxy_id": "string",
    "state": "active | cooldown | banned",
    "consecutive_failures": "integer",
    "cooldown_until": "ISO8601 | null",
    "last_check": "ISO8601 | null",
    "last_success_at": "ISO8601 | null",
    "last_failure_at": "ISO8601 | null",
    "latency_ms_avg": "float",
    "latency_ms_last": "float",
    "success_count": "integer",
    "failure_count": "integer",
    "last_error": "string",
    "is_available": "boolean"
  }
}
```

**说明**: `is_available` 为计算属性，代理当前是否可被使用（state=active 且非 cooldown 中）。

**错误响应**:
```json
{
  "error": "Proxy not found",
  "proxy_id": "string"
}
```

---

### tool: proxy_create

添加一个新的代理到全局池。

**Input Schema**:
```json
{
  "id": "string | null",           // null=自动生成 UUID
  "url": "string (required)",
  "proxy_type": "string (optional, default=http)",
  "username": "string | null",
  "password": "string | null",
  "region": "string | null",
  "tags": ["string"] | null,
  "notes": "string | null"
}
```

**约束**:
- `url` 必须能解析出 scheme + host（host 可带端口）
- `proxy_type` 限定 `http` | `https` | `socks5`

**Output Schema**:
```json
{
  "proxy_id": "string",
  "created": true
}
```

---

### tool: proxy_update

更新已有代理的配置。

**Input Schema**:
```json
{
  "proxy_id": "string (required)",
  "url": "string | null",
  "proxy_type": "string | null",
  "username": "string | null",
  "password": "string | null",
  "region": "string | null",
  "tags": ["string"] | null",
  "enabled": "boolean | null",
  "notes": "string | null"
}
```

**说明**: 只传需要改的字段，`null` 不变。

**Output Schema**:
```json
{
  "proxy_id": "string",
  "updated": true
}
```

---

### tool: proxy_delete

从全局池中删除代理。

**Input Schema**:
```json
{
  "proxy_id": "string (required)"
}
```

**Output Schema**:
```json
{
  "proxy_id": "string",
  "deleted": true
}
```

---

### tool: proxy_health_check

对指定代理发起健康检查（HTTP GET 测试），并更新健康记录。

**Input Schema**:
```json
{
  "proxy_id": "string (required)",
  "test_url": "string (optional, default=https://www.google.com)",
  "timeout": "integer (optional, default=10)" // 超时秒数
}
```

**Output Schema**:
```json
{
  "proxy_id": "string",
  "reachable": "boolean",
  "latency_ms": "float | null",
  "state": "active | cooldown | banned",
  "last_check": "ISO8601",
  "error": "string | null"
}
```

**说明**: 健康检查成功后 `success_count++`，失败后 `failure_count++` 且 `consecutive_failures++`。连续失败 3 次以上代理会被标记为 `banned`。

---

### tool: proxy_bulk_import

从文件批量导入代理。

**Input Schema**:
```json
{
  "source_path": "string (required)",  // 文件路径
  "format": "txt | csv (optional, default=txt)",
  "default_tags": ["string"] | null    // 所有代理的默认标签
}
```

**格式说明**:

**txt 格式**（每行一个代理）:
```
http://user:pass@host:port
https://host:port:username:password
socks5://host:port
```

**csv 格式**（需包含 header 行）:
```csv
url,proxy_type,username,password,region,tags
http://user:pass@103.72.145.67:3000,http,user,pass,US,"residential,datacenter"
```

**Output Schema**:
```json
{
  "imported": "integer",   // 成功导入数量
  "skipped": "integer",    // 跳过的数量（重复/格式错误）
  "total": "integer",
  "proxy_ids": ["string"]
}
```

---

### tool: proxy_reset_health

重置代理的健康状态（清除失败计数，恢复 `active`）。

**Input Schema**:
```json
{
  "proxy_id": "string (required)",
  "state": "active | null (optional, default=active)"
}
```

**Output Schema**:
```json
{
  "proxy_id": "string",
  "reset": true,
  "previous_state": "string",
  "new_state": "string"
}
```

**说明**: 人工确认代理恢复后，手动重置用这个。

---

## ProxyHealthState 枚举

| 状态 | 含义 | is_available |
|------|------|-------------|
| `active` | 健康可用 | ✅ |
| `cooldown` | 临时冷却（防封） | ❌（cooldown 到期后恢复） |
| `banned` | 已确认封禁 | ❌ |

---

## URL 格式规范

代理 URL 支持以下格式：

| 格式 | 示例 |
|------|------|
| 无认证 | `http://103.72.145.67:3000` |
| URL 内嵌认证 | `http://user:pass@103.72.145.67:3000` |
| SOCKS5 | `socks5://103.72.145.67:3000` |
| 带路径 | `http://host:port/path`（path 会被忽略） |

显式 `username`/`password` 字段优先于 URL 内嵌认证。

---

## MCP 集成示例

### Claude Desktop

```json
{
  "mcpServers": {
    "webauto-proxy": {
      "command": "python",
      "args": [
        "-m", "webauto.mcp.proxy_server"
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
    "webauto-proxy": {
      "command": "uvicorn",
      "args": [
        "webauto.mcp.proxy_server:app",
        "--host", "127.0.0.1",
        "--port", "8081"
      ],
      "env": {
        "WEBAUTO_BASE_DIR": "~/.cache/webauto"
      }
    }
  }
}
```

---

*文档版本: v1.0 | 生成时间: 2026-07-14 | Task: T-083*
