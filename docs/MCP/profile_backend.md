# MCP profile_backend — 工具清单与 Schema 文档

> **MCP Server**: `webauto-profile`  
> **协议版本**: MCP 1.0  
> **后端模块**: `Core/Profile/store.py` + `Core/Profile/profile.py`  
> **状态**: T-082 完成

---

## 概览

`profile_backend` 处理浏览器配置单元（Profile）的增删改查。

**Profile** 包含：指纹配置、网络代理配置、标签、生命周期状态。

**数据目录**: `~/.cache/webauto/profiles/<profile_id>/`

---

## 工具清单（8 个）

| # | 工具名 | 说明 |
|---|--------|------|
| 1 | `profile_list` | 列出所有 Profile |
| 2 | `profile_get` | 获取单个 Profile 详情 |
| 3 | `profile_create` | 创建新 Profile |
| 4 | `profile_update` | 更新 Profile 配置 |
| 5 | `profile_delete` | 删除 Profile |
| 6 | `profile_warmup` | 预热 Profile（生成 user-data） |
| 7 | `profile_export` | 导出 Profile 为 .zip |
| 8 | `profile_import` | 从 .zip 导入 Profile |

---

## Schema 定义

### tool: profile_list

列出所有 Profile 摘要列表。

**Input Schema** (`input` JSON):
```json
{
  // 无需参数
}
```

**Output Schema**:
```json
{
  "profiles": [
    {
      "id": "string",
      "name": "string",
      "status": "ready | running | cooldown | banned | archived",
      "tags": ["string"],
      "last_used": "ISO8601 | null",
      "created_at": "ISO8601"
    }
  ],
  "total": "integer"
}
```

**示例**:
```json
{
  "profiles": [
    {
      "id": "profile-001",
      "name": "US 账号池-A",
      "status": "ready",
      "tags": ["us", "residential"],
      "last_used": "2026-07-10T08:30:00Z",
      "created_at": "2026-07-01T12:00:00Z"
    }
  ],
  "total": 1
}
```

---

### tool: profile_get

获取单个 Profile 的完整配置。

**Input Schema**:
```json
{
  "profile_id": "string (required)" // Profile 唯一标识
}
```

**Output Schema**:
```json
{
  "profile": {
    "id": "string",
    "name": "string",
    "status": "string",
    "tags": ["string"],
    "fingerprint": {
      "platform": "string",
      "user_agent": "string",
      "viewport": { "width": "integer", "height": "integer" },
      "timezone": "string",
      "locale": "string",
      "ua_mask_type": "string"
    },
    "network": {
      "proxy_url": "string | null",
      "proxy_username": "string | null",
      "proxy_password": "string | null",
      "proxy_type": "http | socks5",
      "geoip_country": "string | null",
      "dns_over_https": "boolean",
      "proxy_pool": ["string"]
    },
    "cooldown_until": "ISO8601 | null",
    "last_used": "ISO8601 | null",
    "created_at": "ISO8601",
    "storage_dir": "string"
  }
}
```

**错误响应**:
```json
{
  "error": "Profile not found",
  "profile_id": "string"
}
```

---

### tool: profile_create

创建一个新的 Profile。

**Input Schema**:
```json
{
  "profile_id": "string (required)",
  "name": "string (optional, default=profile_id)",
  "tags": ["string"] | null,
  "fingerprint": {
    "platform": "string | null",
    "user_agent": "string | null",
    "viewport": { "width": "integer", "height": "integer" } | null,
    "timezone": "string | null",
    "locale": "string | null",
    "ua_mask_type": "string | null"
  } | null,
  "network": {
    "proxy_url": "string | null",
    "proxy_username": "string | null",
    "proxy_password": "string | null",
    "proxy_type": "string | null",
    "geoip_country": "string | null",
    "dns_over_https": "boolean | null",
    "proxy_pool": ["string"] | null
  } | null
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "created": true,
  "storage_dir": "string"
}
```

**错误响应**:
```json
{
  "error": "Profile already exists",
  "profile_id": "string"
}
```

---

### tool: profile_update

更新已有 Profile 的配置（原子写，不影响 user-data）。

**Input Schema**:
```json
{
  "profile_id": "string (required)",
  "name": "string | null",
  "tags": ["string"] | null,
  "fingerprint": { ...same as create... } | null,
  "network": { ...same as create... } | null,
  "status": "ready | cooldown | banned | archived | null"
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "updated": true
}
```

**说明**: 只传需要改的字段，`null` 不变。`status` 可以单独改。

---

### tool: profile_delete

删除 Profile。

**Input Schema**:
```json
{
  "profile_id": "string (required)",
  "wipe_storage": "boolean (optional, default=true)"
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "deleted": true,
  "wiped": "boolean"
}
```

**说明**: `wipe_storage=true`（默认）连 user-data 一起删，不可恢复。

---

### tool: profile_warmup

预热 Profile——提前创建 user-data 目录和 Chromium 配置文件。

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
  "warmed_up": true,
  "user_data_dir": "string"
}
```

**说明**: 调用后 Chromium User Data Directory 会被创建，下次启动浏览器不用等初始化了。

---

### tool: profile_export

导出 Profile 为 .zip 包（含 config + fingerprint + user-data）。

**Input Schema**:
```json
{
  "profile_id": "string (required)",
  "target_path": "string (required)" // 导出路径，如 "/tmp/profile-001.zip"
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "exported": true,
  "path": "string",
  "size_bytes": "integer"
}
```

**错误响应**:
```json
{
  "error": "Profile not found",
  "profile_id": "string"
}
```

---

### tool: profile_import

从 .zip 包导入 Profile。

**Input Schema**:
```json
{
  "source_path": "string (required)", // zip 文件路径
  "new_id": "string | null"           // null=保持原 ID
}
```

**Output Schema**:
```json
{
  "profile_id": "string",
  "imported": true,
  "storage_dir": "string"
}
```

**说明**: 若 `new_id` 与原 ID 不同，Profile 的 id 和 name 都会改成新值。

---

## ProfileStatus 枚举

| 状态 | 含义 | 可借 |
|------|------|------|
| `ready` | 已配置可启动 | ✅ |
| `running` | 正在使用中 | ❌ |
| `cooldown` | 暂时冷却（防风控） | ❌ |
| `banned` | 已封禁 | ❌ |
| `archived` | 归档不再用 | ❌ |

---

## 网络配置字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `proxy_url` | string\|null | 完整代理 URL，如 `http://user:pass@host:port` |
| `proxy_username` | string\|null | 显式认证用户名（优先于 URL 内嵌） |
| `proxy_password` | string\|null | 显式认证密码（优先于 URL 内嵌） |
| `proxy_type` | string | `http`（默认）或 `socks5` |
| `geoip_country` | string\|null | ISO 国家码，如 `US`、`CN`、`JP` |
| `dns_over_https` | boolean | 是否启用 DoH（默认 true） |
| `proxy_pool` | string[] | 备用代理列表（失败时轮换） |

---

## MCP 集成示例

### Claude Desktop (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "webauto-profile": {
      "command": "python",
      "args": [
        "-m", "webauto.mcp.profile_server"
      ],
      "env": {
        "WEBAUTO_BASE_DIR": "~/.cache/webauto"
      }
    }
  }
}
```

### Cursor (.cursor/mcp.json)

```json
{
  "mcpServers": {
    "webauto-profile": {
      "command": "uvicorn",
      "args": [
        "webauto.mcp.profile_server:app",
        "--host", "127.0.0.1",
        "--port", "8080"
      ],
      "env": {
        "WEBAUTO_BASE_DIR": "~/.cache/webauto"
      }
    }
  }
}
```

---

*文档版本: v1.0 | 生成时间: 2026-07-14 | Task: T-082*
