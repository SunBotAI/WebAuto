# WebAuto 协作文档

> 状态：CURRENT
> 最后更新：2026-08-27
> 用途：约束 AI 读取、生成和更新项目文档，并为人提供统一的项目进度入口。

## 1. 人应该先看什么

按顺序掌握项目情况：

1. [PROJECT_STATUS.md](./02-项目执行/PROJECT_STATUS.md)：当前做到哪里、缺什么、下一步。
2. [WebAuto 最终方案 §17](./01-项目方案/WebAuto-最终方案.md)：唯一完整执行计划（B0—B4）。
3. [TASKS.md](./02-项目执行/TASKS.md)：具体任务、状态和证据。
4. [QUALITY_STATUS.md](./04-测试验收/QUALITY_STATUS.md)：当前质量是否有验证证据。

遇到具体技术或运维问题，再进 03-技术文档、05-部署运维。

## 2. 目录结构

```text
docs/
├── README.md
├── 01-项目方案/
│   └── WebAuto-最终方案.md   # 唯一方案 + 唯一执行计划（§17）
├── 02-项目执行/
│   ├── PROJECT_STATUS.md
│   ├── TASKS.md
│   ├── WORKLOG.md
│   ├── RISKS.md
│   └── CHANGELOG.md
├── 03-技术文档/
│   ├── ARCHITECTURE.md
│   ├── TECH_DEBT.md
│   └── ADR/
├── 04-测试验收/
│   ├── TEST_PLAN.md
│   └── QUALITY_STATUS.md
└── 05-部署运维/
    ├── DEPLOYMENT.md
    └── SRE.md
```

一级目录按开发流程划分：**方案 → 执行 → 技术 → 测试 → 部署**。旧历史报告（v3.1/v3.2 的 Browser Use、垂直闭环、PG/Redis 时代）已删除，不再保留。

## 3. 每个文件回答什么

| 文件 | 唯一职责 |
|---|---|
| WebAuto-最终方案.md | 最终做成什么、为什么这样设计（§17 是唯一完整执行计划） |
| PROJECT_STATUS.md | 面向人的项目状态总览 |
| TASKS.md | 跨模块统一任务状态（任务 ID 与最终方案 §17 一致） |
| WORKLOG.md | 产生有效结果的 AI 工作记录 |
| RISKS.md | 不确定的未来事件、缓解和待决策项 |
| CHANGELOG.md | 已完成的重要产品与架构变化 |
| ARCHITECTURE.md | 当前架构快照 |
| TECH_DEBT.md | 尚未解决的结构性技术问题（迁移清理台账） |
| TEST_PLAN.md | 应该怎么测试和验收 |
| QUALITY_STATUS.md | 最近一次有效测试证据与结论 |
| DEPLOYMENT.md | 部署、发布、回滚与备份 |
| SRE.md | 监控、告警、巡检与应急 |

一个事实只允许有一个主要维护文件，其他文档只链接，不重复复制完整状态。

## 4. AI 开始工作前

必须依次读取：本文件 → PROJECT_STATUS.md → 最终方案 §17 → TASKS.md → 相关技术/运维文档 → 相关源码、测试和配置。

如果文档与代码冲突：

- 当前实现以代码、Schema、迁移和实际验证为准；
- 项目目标以最终方案为准；
- AI 必须修正文档，不允许静默忽略冲突；
- 没有运行证据时不得把质量状态写成 PASS。

## 5. 更新触发表

| 发生的事情 | 必须更新 |
|---|---|
| 产品目标或范围变化 | 最终方案、PROJECT_STATUS |
| 开始新阶段 | TASKS、PROJECT_STATUS |
| 任务完成 | TASKS、PROJECT_STATUS、WORKLOG |
| 发现阻塞 | TASKS、RISKS、PROJECT_STATUS |
| 修复技术债 | TECH_DEBT、TASKS、CHANGELOG |
| 完成测试 | QUALITY_STATUS |
| 部署或监控变化 | DEPLOYMENT 或 SRE |
| 发布重要版本 | CHANGELOG、QUALITY_STATUS、PROJECT_STATUS |

## 6. 文档状态

| 状态 | 含义 |
|---|---|
| CURRENT | 当前有效，AI 必须维护 |
| READY | 已具备执行条件，等待启动 |
| DRAFT | 尚未确认，不得作为完成事实 |
| IN_PROGRESS | 正在实施 |
| NEEDS_VERIFICATION | 有静态依据，缺最新运行验证 |
| ARCHIVED | 已失效，仅用于追溯 |

## 7. 禁止事项

- 不在 docs 保存逐次测试截图、trace、视频、JSON 或完整日志。
- 不为一次修复创建 REPORT、REVIEW、AUDIT 等永久文件。
- 不复制代码配置值形成第二事实来源。
- 不把规划中的能力描述成已经完成。
- 不使用历史测试报告证明当前版本通过。
- 不在多个状态文件中维护互相冲突的项目结论。
- 不创建只有 README 的空目录。
