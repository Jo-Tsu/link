# Smallink 当前记忆产品逻辑与代码结构

本文只描述当前仓库中的真实实现，不把 PRD 目标、未来 Postgres 架构或尚未接线的能力写成已上线功能。

## 1. 当前产品定位

Smallink 当前把记忆拆成三个不同层次：

1. **工作上下文**
   - 当前会话中的消息、计划、工具调用和任务过程。
   - 由会话与运行时模块维护。
   - 不等同于长期个人记忆。
2. **原始记忆源数据**
   - 用户输入、Assistant 输出、工具记录和连接器同步数据。
   - 存在 `sensory_records`。
   - 保留来源、会话、项目路径、时间和内容哈希。
3. **长期记忆**
   - 从原始数据提炼出的长期事实、偏好、项目背景和决策。
   - 当前以 `memories` 表保存。
   - 分为 `pending` 与 `active`。

当前产品真正打通的是：

```text
本地会话 / Smallink 运行时
→ 原始数据采集
→ sensory_records
→ 手动触发 MemoryPipeline
→ pending memories
```

当前尚未打通：

```text
pending memories
→ 查看完整来源
→ 人工确认 / 编辑 / 忽略 / 合并
→ active memories
→ 按任务检索
→ 智能体引用并记录使用版本
```

## 2. 当前真实数据状态

当前默认数据目录为：

```text
~/.config/link/
```

主要 SQLite 数据库为：

```text
~/.config/link/link.db
```

当前本机数据状态：

| 来源 | 原始记录 | 会话数 | 状态 |
|---|---:|---:|---|
| TRAE CLI | 72 | 12 | 全部 pending |
| Smallink runtime | 5 | 1 | 全部 pending |
| 合计 | 77 | 13 | 尚未生成 memory |

数据库完整性检查为 `ok`。

这些数据已经进入原始层，但尚未运行可靠的治理与确认闭环，因此不能视为可供智能体使用的正式记忆。

## 3. 数据采集逻辑

## 3.1 Smallink 自身运行时采集

入口：

```text
SessionManager.tracked_engine_events()
```

实现位置：

```text
smallink/server/manager.py
```

采集内容包括：

- 用户输入。
- 连接器输入。
- Assistant 完整输出。
- 工具提议。
- 工具结果。
- 运行错误。

采集时会写入：

```text
SQLiteSensoryStore
→ sensory_records
```

每条记录保留：

- `source_type`
- `connector_id`
- `account_id`
- `external_id`
- `content_type`
- `raw_content`
- `normalized_content`
- `occurred_at`
- `project_path`
- `conversation_id`
- `content_hash`
- `sensitivity`
- `governance_status`
- `metadata`
- `source_locator`

## 3.2 通用外部采集入口

REST API：

```text
POST /v1/sensory-records
```

调用链：

```text
server/app.py
→ SessionManager.ingest_sensory_record()
→ SQLiteSensoryStore.add()
```

当前幂等约束为：

```text
source_type + external_id + content_hash
```

相同来源、相同外部编号、相同内容不会重复写入。

## 3.3 Codex 数据连接器

默认数据目录：

```text
~/.codex/sessions
```

用户在桌面端选择 `~/.codex` 后，Smallink 保存规范化后的 sessions 路径。

调用链：

```text
AddConnectionModal
→ POST /v1/connectors/codex/connect
→ POST /v1/connectors/codex/sync
→ SessionManager.sync_codex()
→ codex_client.read_sessions()
→ sensory_records
```

解析规则：

- 读取 `rollout-*.jsonl`。
- 只保留 user 与 assistant 消息。
- 过滤已知权限协议、系统指令和环境上下文。
- 一个用户消息与其后连续 Assistant 消息组成一个 turn。
- 每个 turn 写成一个 `codex_turn` 原始记录。

## 3.4 TraeX / TRAE CLI 数据连接器

默认数据目录：

```text
~/.trae/cli/sessions
```

调用链：

```text
AddConnectionModal
→ POST /v1/connectors/traex/connect
→ POST /v1/connectors/traex/sync
→ SessionManager.sync_traex()
→ traex_client.read_sessions()
→ sensory_records
```

额外规则：

- 只导入 `thread_source=user` 的主会话。
- 旧格式缺少 `thread_source` 时使用兼容路径。
- 排除子智能体内部线程。
- 优先截断到最后一个 `task_complete`。
- 当前仍在追加的尾部轮次等待下一次同步。
- 每个 turn 写成一个 `traex_turn` 原始记录。

当前本机同步结果：

```text
52 个 rollout 文件
→ 12 个用户主会话
→ 72 个已完成轮次
→ 再次同步新增 0
```

## 4. 原始数据层

代码：

```text
smallink/sensory/models.py
smallink/sensory/store.py
```

核心对象：

```text
SensoryRecord
SQLiteSensoryStore
```

设计目标：

- 原始内容不可被 AI 覆盖。
- 可以追溯来源。
- 连接器重复同步保持幂等。
- 为后续治理任务提供事实输入。

当前状态字段：

```text
governance_status = pending
```

当前实现没有完整的状态推进逻辑，因此记录不会自动进入：

- `processing`
- `processed`
- `skipped`
- `failed`

## 5. 记忆提炼管道

代码：

```text
smallink/memory/pipeline.py
```

入口：

```text
POST /v1/memory/pipeline/run
```

调用链：

```text
server/app.py
→ SessionManager.run_memory_pipeline()
→ MemoryPipeline.process()
```

模型选择：

```text
model_for_purpose("memory")
```

如果没有模型标记为 memory，则回退到默认模型。

管道一次模型调用完成三个动作：

1. **清洗**
   - 从原始记录中提取值得长期保存的事实。
2. **标记**
   - 为每条事实选择记忆类型。
3. **分层**
   - 选择 global、workspace 或 session scope。

输出格式：

```json
{
  "facts": [
    {
      "content": "长期事实",
      "memory_type": "user_preference",
      "scope": "global"
    }
  ]
}
```

管道产物统一写入：

```text
status = pending
```

因此不会被普通对话当作正式记忆使用。

## 6. 记忆类型

当前共有十种类型：

| 类型 | 含义 |
|---|---|
| `user_preference` | 用户长期偏好 |
| `project_context` | 项目目标、范围、约束和阶段 |
| `product_decision` | 已确认的产品或技术决策 |
| `reasoning_process` | 用户评估方案和形成结论的方式 |
| `open_question` | 仍需继续解决的重要问题 |
| `reusable_pattern` | 可重复使用的方法 |
| `work_habit` | 反复出现的工作方式 |
| `artifact_summary` | 报告、代码或交付物摘要 |
| `document_insight` | 文档中的长期结论 |
| `life_memory` | 项目工作之外的个人长期信息 |

类型定义当前分别存在于：

```text
smallink/memory/pipeline.py
surfaces/gui/src/components/MemoryView.tsx
```

前后端需要人工保持一致。

## 7. 记忆作用域

当前支持三种 scope：

| Scope | 含义 |
|---|---|
| `global` | 对用户所有任务都有效 |
| `workspace` | 只对某个项目目录有效 |
| `session` | 只与某个会话有关 |

默认回退规则：

- 原始记录有 `project_path`：使用 workspace。
- 没有 `project_path`：使用 global。

## 8. 记忆存储

代码：

```text
smallink/memory/base.py
smallink/memory/sqlite_store.py
```

核心对象：

```text
MemoryItem
MemoryStore
SQLiteMemoryStore
```

`memories` 当前保存：

- `id`
- `scope`
- `key`
- `content`
- `workspace`
- `session_id`
- `created_at`
- `status`
- `updated_at`
- `source_record_id`

状态语义：

| 状态 | 当前含义 |
|---|---|
| `pending` | AI 管道产物，等待未来人工治理 |
| `active` | 可以被读取并注入到智能体上下文 |
| `archived` | 类型中有定义意图，但当前没有完整产品操作 |

`memory_history` 保存 add、update、delete 的内容变化记录。

## 9. 智能体如何读取记忆

代码：

```text
smallink/agent.py
```

构建引擎时：

1. 读取 global active memories。
2. 如果存在 workspace，再读取当前 workspace 的 active memories。
3. 格式化为只读上下文。
4. 追加到 system instructions。

读取逻辑：

```text
memory_store.list(scope=GLOBAL)
memory_store.list(scope=WORKSPACE, workspace=current_workspace)
```

由于 `list()` 默认只返回 `status='active'`，pending 记忆不会进入 prompt。

当前默认智能体不注册旧的直接写记忆工具，因此模型不能绕过治理流程直接创建正式记忆。

## 10. 前端记忆页

代码：

```text
surfaces/gui/src/components/MemoryView.tsx
```

首页展示：

- 正式记忆总数。
- Global 记忆数量。
- Project 记忆数量。
- 原始源数据总数，并可进入源数据列表。
- 十种记忆类型卡片。

页面同时请求：

```text
GET /v1/memory
GET /v1/memory?status=pending
GET /v1/sensory-records/stats
```

当前 pending 区域只支持：

- 查看列表。
- 查看内容。
- 查看类型。
- 查看 scope。
- 查看创建时间。
- 明确提示当前版本为只读候选草稿，不把未实现的确认动作伪装成可用能力。

当前源数据区域支持：

- 按来源筛选。
- 按治理状态筛选。
- 搜索内容、项目和会话。
- 查看来源、会话、项目、时间、原始内容和来源位置。
- 加载失败时显示可重试错误。

当前不支持：

- 生成候选。
- 确认。
- 编辑后确认。
- 忽略。
- 合并。
- 查看完整来源。
- 归档与恢复。

连接器导入交互当前区分：

- 选择文件夹。
- 授权连接。
- 扫描和导入。
- 完成。
- 已连接但导入失败。

部分失败时保留真实“已连接”状态，并提供重试导入；成功后可以进入记忆源数据页查看结果。

## 11. 模型用途配置

代码：

```text
smallink/server/manager.py
surfaces/gui/src/components/ModelChecklist.tsx
```

当前可保存三个标签：

```text
chat
memory
title
```

实际接线情况：

| 用途 | 是否真正接线 |
|---|---|
| memory | 是，记忆管道调用 |
| chat | 否，只保存配置 |
| title | 否，只保存配置 |

因此当前真正有效的是 memory 模型用途。

## 12. 当前代码结构

```text
smallink/
├── sensory/
│   ├── models.py          # 原始记录领域模型
│   └── store.py           # sensory_records SQLite 存储
├── memory/
│   ├── base.py            # MemoryItem、Scope、MemoryStore
│   ├── sqlite_store.py    # memories、memory_history
│   ├── pipeline.py        # 清洗、标记、分层
│   └── tools.py           # 旧直接写工具，默认运行时不注册
├── connectors/
│   ├── codex_client.py    # Codex rollout 解析
│   ├── traex_client.py    # TRAE 主线程与完成边界过滤
│   ├── setup.py           # 连接、断开、连接状态
│   ├── descriptors.py     # 连接器目录定义
│   └── cli.py             # sync-codex / sync-traex CLI
├── server/
│   ├── manager.py         # 采集、连接器同步、管道编排
│   └── app.py             # REST API
└── agent.py               # active memory 注入

surfaces/gui/src/
├── api.ts
├── components/
│   ├── MemoryView.tsx
│   ├── ModelChecklist.tsx
│   └── connectors/
│       ├── AddConnectionModal.tsx
│       ├── ConnectorsList.tsx
│       └── ConnectorsSection.tsx
└── connectors/
    └── registry.tsx
```

## 13. 当前 API

### 原始数据

```text
GET  /v1/sensory-records
GET  /v1/sensory-records/stats
GET  /v1/sensory-records/{record_id}
POST /v1/sensory-records
```

### 连接器同步

```text
POST /v1/connectors/codex/sync
POST /v1/connectors/traex/sync
```

### 记忆

```text
GET  /v1/memory
GET  /v1/memory?status=pending
GET  /v1/memory?status=all
POST /v1/memory/pipeline/run
POST /v1/memory
```

其中 `POST /v1/memory` 当前固定返回治理要求错误，不提供正式记忆创建能力。

## 14. 当前可信边界

已经实现并验证：

- Smallink runtime 原始数据采集。
- 通用 sensory ingest。
- Codex 本地会话导入。
- TRAE 主会话导入。
- TRAE 子智能体排除。
- TRAE 完成轮次截断。
- 原始记录持久化与来源统计。
- LLM 提炼到 pending memory。
- pending 与 active 默认隔离。
- active global/workspace memory 只读注入。

尚未达到可交付闭环：

- 敏感数据发送策略。
- 稳定的 source processing 状态机。
- 并发幂等。
- 空结果和失败重试。
- 候选独立领域模型。
- 人工治理。
- 正式记忆事务。
- 来源查看。
- 检索与引用记录。
- 完整 E2E。

## 15. 当前产品状态定义

当前最准确的产品状态是：

> Smallink 已经实现本地会话与运行时数据的原始采集层，并具备实验性的记忆提炼管道；正式个人记忆的治理、确认、检索和使用闭环尚未完成。

因此在后续迭代中，应把下面两件事严格区分：

```text
数据已经同步
≠
记忆已经生成并可被智能体使用
```
