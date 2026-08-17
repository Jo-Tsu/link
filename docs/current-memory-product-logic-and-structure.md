# Smallink 当前记忆产品逻辑与代码结构

本文只描述 `0.2.0` 当前代码，不把 Postgres、向量检索、知识库或项目空间等目标能力写成已上线功能。

## 1. 当前闭环

Smallink 将数据分为四层：

1. **工作上下文**：当前会话、计划、工具和运行过程。
2. **原始事实**：不可变的 `sensory_records`。
3. **候选记忆**：AI 提炼后、等待用户决定的 `memory_candidates`。
4. **正式记忆**：用户接受后写入 `memories`，并保存版本、来源和决策。

当前已经打通：

```text
Smallink / Codex / TRAE
→ sensory_records
→ GovernanceTask 原子领取
→ AI 提炼
→ MemoryCandidate + CandidateSource
→ 接受 / 编辑后接受 / 合并 / 忽略
→ Memory + MemoryVersion + MemorySource + GovernanceDecision
→ 作用域过滤 + 关键词相关性 + 字符预算
→ active global/workspace memory 注入智能体上下文
→ memory_usage 记录使用版本
```

当前仍未完成：

```text
向量 / 混合检索
→ Token 级预算与 ContextBundle
→ 效果反馈
```

## 2. 数据位置

默认状态目录仍为兼容路径：

```text
~/.config/link/
```

主要业务库：

```text
~/.config/link/link.db
```

文档不再记录某一台机器的实时行数。当前数量以客户端记忆页和以下 API 为准：

```text
GET /v1/sensory-records/stats
GET /v1/memory
GET /v1/memory/candidates
```

## 3. 原始事实采集

Smallink 运行时从 `SessionManager.tracked_engine_events()` 采集：

- 用户和连接器输入；
- Assistant 最终输出；
- 工具提议和结果；
- 运行错误。

运行时数据库写入通过线程池执行，不阻塞 FastAPI 事件循环。所有 SQLite Store 使用统一连接策略：

```text
WAL
busy_timeout=15000
synchronous=NORMAL
foreign_keys=ON
```

每条 `sensory_records` 保留来源、内容、项目、会话、哈希、敏感级别、治理状态和来源位置。

### 通用采集入口

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
governance_status =
  pending | processing | processed | skipped | failed
```

管道通过 `BEGIN IMMEDIATE` 在数据库内原子领取，避免两个 worker 同时处理同一条记录。失败项保留错误、次数和时间，可显式重试；空结果进入 `skipped`，不会反复调用模型。

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

管道产物写入独立的 `memory_candidates`，不会直接写正式记忆。

敏感策略：

- `secret`：禁止发送模型；
- `sensitive`：默认只允许本地模型，云模型需显式许可；
- 常见密码、Token 和 API key 模式在发送前脱敏；
- Provider/解析失败只记录 failed，不把原文固化成候选。

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

正式 `memories` 保存：

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

候选与正式记忆分离。接受候选时，在同一 SQLite 事务中创建正式记忆、版本、来源和决策；编辑后接受保存编辑结果；合并会更新目标记忆并追加版本；忽略只保存决策。

当前表包括：

- `governance_tasks`
- `governance_task_records`
- `memory_candidates`
- `candidate_sources`
- `governance_decisions`
- `memory_versions`
- `memory_sources`
- `memory_usage`

## 9. 智能体如何读取记忆

代码：

```text
smallink/agent.py
```

每个回合组装上下文时：

1. 读取 global active memories。
2. 如果存在 workspace，再读取当前 workspace 的 active memories。
3. 从最新用户消息提取关键词并排序相关记忆。
4. 在条数和字符预算内选择记忆。
5. 作为临时只读 context 注入，不写回会话历史。
6. 将 memory_id、version_id、session 和 workspace 写入 `memory_usage`。

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

页面主要请求：

```text
GET /v1/memory
GET /v1/memory/candidates
GET /v1/sensory-records/stats
```

候选区域支持：

- 生成候选和重试失败项；
- 查看类型、范围、模型和完整来源；
- 接受；
- 编辑后接受；
- 合并到已有正式记忆；
- 忽略。

当前源数据区域支持：

- 按来源筛选。
- 按治理状态筛选。
- 服务端搜索内容、项目和会话；
- 分页；
- 查看来源、会话、项目、时间、原始内容和来源位置。
- 加载失败时显示可重试错误。
- 删除单条源记录。

当前不支持：

- 归档与恢复。
- 候选批量操作。
- 正式记忆冲突视图。
- 向量检索和关系视图。

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
DELETE /v1/sensory-records
```

### 连接器同步

```text
POST /v1/connectors/codex/sync
POST /v1/connectors/traex/sync
GET  /v1/connectors/{name}/sync-status
```

### 记忆

```text
GET  /v1/memory
GET  /v1/memory/candidates
GET  /v1/memory/candidates/{candidate_id}
POST /v1/memory/candidates/{candidate_id}/decision
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
- 连接前目录探测；
- SyncJob、水位和最后同步状态；
- 原始记录服务端搜索、分页与删除；
- 原子治理状态机和失败重试；
- 敏感数据发送策略与脱敏；
- 独立候选模型；
- 接受、编辑、合并和忽略；
- 正式记忆版本、来源和决策；
- active global/workspace memory 只读注入。

后续缺口：

- 向量 / 混合检索和 Token 级 ContextBundle；
- 正式记忆冲突处理；
- 归档恢复和批量治理；
- Postgres / pgvector；
- 记忆使用效果反馈。

## 15. 当前产品状态定义

当前最准确的产品状态是：

> Smallink 已完成从原始数据到人工确认正式记忆的本地闭环，并具备首版相关性检索、上下文预算和使用版本记录；当前主要缺口是向量/混合检索、冲突治理和使用效果反馈。

因此在后续迭代中，应把下面两件事严格区分：

```text
数据已经同步
≠
记忆已经生成并可被智能体使用
```
