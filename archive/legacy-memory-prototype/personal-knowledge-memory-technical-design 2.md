# link 技术架构设计

更新日期：2026-07-12

## 1. 当前架构结论

当前 link 使用轻量本地架构：

- 前端：React + TanStack Router / TanStack Start。
- 服务端：`src/server.ts` 内的本地 API handler。
- 数据库：Postgres + pgvector。
- 稳定运行：Docker Compose，包含 `link-app` 和 `link-postgres`。
- 正式记忆层：`memory_hierarchy_nodes` + `memory_cards`。
- 原始数据层：`sensory_records`。
- 通用治理层：`governance_tasks` + `governance_task_records` + `governance_candidates` + `governance_candidate_sources`。
- mem0：不作为运行依赖，不写入，不展示同步状态。

第二阶段专项技术方案：

- `/Users/bytedance/Downloads/Dream Builder/docs/governance-task-system-phase2-prd.md`
- `/Users/bytedance/Downloads/Dream Builder/docs/governance-task-system-phase2-technical-design.md`

第二阶段目标是把 Codex 数据治理升级为通用数据治理任务系统：当前先适配 Codex，数据库表、API 和候选生成器模型面向后续所有连接器。

```mermaid
flowchart TB
  subgraph Client["前端"]
    Home["/ 工作台"]
    Settings["/settings"]
    Codex["/codex"]
    Governance["/governance"]
    CodexGov["/governance/codex"]
    Memory["/memory"]
    Knowledge["/knowledge 空态"]
    Graph["/graph 空态"]
  end

  subgraph API["src/server.ts API"]
    Sync["POST /api/codex/sync"]
    ConnectorStatus["GET /api/connectors/status"]
    SourceOrigins["GET /api/data-sources/origins"]
    Sensory["GET /api/sensory-records"]
    GovState["GET /api/governance/codex/state"]
    GovTasks["GET /api/governance/tasks"]
    GovRecords["GET /api/governance/tasks/:id/records"]
    GovCandidates["GET /api/governance/tasks/:id/candidates"]
    GovBatch["POST /api/governance/candidates/batch"]
    GovComplete["POST /api/governance/tasks/:id/complete"]
    MemoryCards["GET /api/memory/cards"]
  end

  subgraph DB["Postgres + pgvector"]
    SR["sensory_records"]
    Tasks["governance_tasks"]
    TaskRecords["governance_task_records"]
    Candidates["governance_candidates"]
    Sources["governance_candidate_sources"]
    Watermark["integration_watermarks"]
    Nodes["memory_hierarchy_nodes"]
    Cards["memory_cards"]
  end

  Settings --> Sync
  Settings --> SourceOrigins
  Codex --> ConnectorStatus
  Codex --> Sensory
  Home --> ConnectorStatus
  Home --> MemoryCards
  Governance --> ConnectorStatus
  Governance --> GovState
  CodexGov --> GovTasks
  CodexGov --> GovRecords
  CodexGov --> GovCandidates
  CodexGov --> GovBatch
  CodexGov --> GovComplete
  Memory --> MemoryCards

  Sync --> SR
  Sync --> Tasks
  Sync --> TaskRecords
  Sync --> Candidates
  Sync --> Sources
  ConnectorStatus --> SR
  SourceOrigins --> SR
  Sensory --> SR
  GovState --> Watermark
  GovTasks --> Tasks
  GovRecords --> TaskRecords
  GovRecords --> SR
  GovCandidates --> Candidates
  GovCandidates --> Sources
  GovBatch --> Candidates
  GovComplete --> Cards
  GovComplete --> Nodes
  GovComplete --> SR
  GovComplete --> Tasks
  GovComplete --> Watermark
  MemoryCards --> Cards
  MemoryCards --> Nodes
```

## 2. 代码结构

| 路径                               | 作用                                                               |
| ---------------------------------- | ------------------------------------------------------------------ |
| `src/server.ts`                    | API 分发、Codex 同步入口、SSR 错误包装                             |
| `src/lib/server-db.ts`             | Postgres 访问、schema 补齐、原始记录入库、治理任务、候选、完成入库 |
| `src/lib/codex-governance.ts`      | `rules_v1` 候选生成算法和类型定义，不直接读取 generated snapshot   |
| `scripts/import-codex-history.mjs` | 只读扫描 Codex 本地历史，生成清洗快照                              |
| `src/routes/index.tsx`             | 工作台，读取真实连接器和记忆统计                                   |
| `src/routes/settings.tsx`          | 设置首页、连接器列表/详情、模型 Provider 配置草案                  |
| `src/routes/codex.tsx`             | Codex 接入状态，读取 DB 统计和最近原始记录                         |
| `src/routes/governance.tsx`        | 数据治理首页，读取真实待治理数量和水位                             |
| `src/routes/governance.codex.tsx`  | Codex 治理任务、候选记忆、原始记录弹窗、完成入库                   |
| `src/routes/memory.tsx`            | 个人记忆库模块卡片                                                 |
| `src/routes/memory.$type.tsx`      | 单个记忆类型详情                                                   |
| `src/routes/knowledge.tsx`         | 当前真实空态                                                       |
| `src/routes/graph.tsx`             | 当前真实空态                                                       |

已删除：

- `src/lib/demo-data.ts`。
- 工作台、知识库、图谱、治理首页中的 demo/mock 数据依赖。

## 3. 数据流

### 3.1 Codex 同步

```mermaid
sequenceDiagram
  participant U as User
  participant S as Settings
  participant API as /api/codex/sync
  participant Script as import-codex-history.mjs
  participant DB as Postgres

  U->>S: 点击同步 Codex 数据
  S->>API: POST /api/codex/sync
  API->>Script: node scripts/import-codex-history.mjs
  Script-->>API: codex-history.generated.json
  API->>DB: saveCodexSensoryRecords
  API->>DB: ensureGovernanceTaskForPendingRecords
  API->>DB: generateGovernanceCandidatesForTask
  DB-->>API: inserted / updated / task / candidates
  API-->>S: 同步结果
```

同步结果写入：

- `src/lib/codex-history.generated.json`
- `sensory_records`
- `governance_tasks`
- `governance_task_records`
- `governance_candidates`
- `governance_candidate_sources`

说明：generated snapshot 只作为同步脚本中间产物保留。`/governance/codex` 前端运行时不再读取 generated snapshot，治理任务和候选记忆从数据库聚合。

### 3.2 通用治理任务完成

```mermaid
sequenceDiagram
  participant U as User
  participant Page as /governance/codex
  participant API as /api/governance/tasks/:id/complete
  participant DB as Postgres

  U->>Page: 忽略 / 纳入记忆 / 编辑 / 合并
  Page->>API: POST /api/governance/candidates/batch
  API->>DB: update governance_candidates
  U->>Page: 完成任务并入库
  Page->>API: POST taskId
  API->>DB: insert/update memory_cards
  API->>DB: ensure memory_hierarchy_nodes
  API->>DB: update sensory_records.status = governed / ignored
  API->>DB: update governance_tasks.status = completed
  API->>DB: update integration_watermarks
  API-->>Page: ok
```

## 4. API 设计

| API                                    | 方法 | 当前用途                                                                        |
| -------------------------------------- | ---- | ------------------------------------------------------------------------------- |
| `/api/health`                          | GET  | 检查服务和数据库连接                                                            |
| `/api/codex/sync`                      | POST | 只读扫描 Codex 本地历史，并写入 `sensory_records`                               |
| `/api/connectors/status`               | GET  | 返回连接器统计、线程数、原始类型分布和待治理数量                                |
| `/api/data-sources/origins`            | GET  | 按来源容器聚合所有数据源头，返回连接器来源、项目路径、来源 URI 和 raw type 分布 |
| `/api/sensory-records`                 | GET  | 分页读取原始池，支持来源、状态、类型、线程、截止时间和搜索过滤                  |
| `/api/governance/codex/state`          | GET  | 读取 Codex 治理水位、已处理线程和最近治理批次                                   |
| `/api/governance/tasks`                | GET  | 分页读取通用治理任务                                                            |
| `/api/governance/tasks/:id`            | GET  | 读取治理任务详情和原始类型分布                                                  |
| `/api/governance/tasks/:id/records`    | GET  | 分页读取当前治理任务关联的原始数据                                              |
| `/api/governance/tasks/:id/candidates` | GET  | 读取当前治理任务候选结果                                                        |
| `/api/governance/candidates/:id`       | GET  | 读取候选详情和引用源头                                                          |
| `/api/governance/candidates/batch`     | POST | 批量忽略、纳入、编辑后纳入或合并候选                                            |
| `/api/governance/tasks/:id/complete`   | POST | 完成治理任务，写入记忆并推进水位                                                |
| `/api/memory/cards`                    | GET  | 读取正式个人记忆                                                                |

### 4.1 `/api/sensory-records` 参数

| 参数               | 说明                                                                         |
| ------------------ | ---------------------------------------------------------------------------- |
| `source`           | 当前为 `codex`                                                               |
| `status`           | `all` / `pending_governance` / `governed` / `ignored` / `archived` / `error` |
| `rawType`          | `all` / `user_input` / `codex_output` / `cli` / `tool` / `skill`             |
| `threadIds`        | 逗号分隔线程 ID，用于限定当前治理任务                                        |
| `occurredTo`       | 截止时间，避免混入同线程后续新增数据                                         |
| `q`                | 搜索原始内容、摘要、线程标题、项目路径                                       |
| `limit` / `offset` | 分页                                                                         |

## 5. 数据库表

### 5.1 当前核心表

| 表                             | 状态     | 说明                                 |
| ------------------------------ | -------- | ------------------------------------ |
| `sensory_records`              | 已使用   | 原始数据池                           |
| `governance_tasks`             | 已使用   | 通用治理任务                         |
| `governance_task_records`      | 已使用   | 任务与原始记录关联                   |
| `governance_candidates`        | 已使用   | 候选记忆/候选资产                    |
| `governance_candidate_sources` | 已使用   | 候选引用源头                         |
| `integration_watermarks`       | 已使用   | Codex 治理水位                       |
| `codex_governance_runs`        | 兼容保留 | 第一阶段历史批次，新流程不再写入     |
| `codex_governance_outputs`     | 兼容保留 | 第一阶段历史输出，新流程不再写入     |
| `memory_hierarchy_nodes`       | 已使用   | 记忆树节点                           |
| `memory_cards`                 | 已使用   | 正式个人记忆                         |
| `knowledge_items`              | 预留     | 知识库未接入真实写入                 |
| `evidence_records`             | 预留     | 证据链未形成独立页面                 |
| `graph_edges`                  | 预留     | 知识图谱未接入真实生成               |
| `codex_threads`                | 预留     | 后续替代 generated snapshot 的线程表 |
| `candidate_memories`           | 不使用   | 已由 `governance_candidates` 替代    |

### 5.2 `sensory_records`

核心字段：

```sql
source TEXT
source_thread_id TEXT
source_container_id TEXT
source_record_id TEXT
source_record_hash TEXT
raw_type TEXT
raw_label TEXT
raw_text TEXT
normalized_text TEXT
summary TEXT
occurred_at TIMESTAMPTZ
synced_at TIMESTAMPTZ
project_path TEXT
thread_title TEXT
source_uri TEXT
sensitivity_level TEXT
noise_level TEXT
metadata JSONB
status TEXT
governance_run_id TEXT
```

索引：

- `idx_sensory_records_source_status`
- `idx_sensory_records_source_hash`
- `idx_sensory_records_container`

去重策略：

- `source_record_hash = sha256(source_record_id)`
- 唯一索引：`(source, source_record_hash)`
- 已治理、已忽略、已归档记录再次同步时不回退为待治理。

### 5.3 `memory_cards`

核心字段：

```sql
id TEXT PRIMARY KEY
hierarchy_id UUID
source_run_id TEXT
source_thread_id TEXT
title TEXT
content TEXT
crystallized_content TEXT
memory_type TEXT
classification_path TEXT[]
state_subject TEXT
state_attribute TEXT
state_from TEXT
state_to TEXT
source_excerpt TEXT
confidence NUMERIC
status TEXT
metadata JSONB
evidence_metadata JSONB
embedding VECTOR(1536)
```

写入规则：

- 只有用户确认纳入、编辑后纳入、合并的候选记忆会写入。
- 忽略的候选记忆不写入 `memory_cards`。
- 写入前通过 `ensureMemoryHierarchyPath` 补齐记忆树路径。
- 写入后通过 `recomputeMemoryHierarchyCounts` 更新祖先节点计数。

## 6. 前端实现边界

### 6.1 已切换为真实数据的页面

- `/`
- `/settings`
- `/codex`
- `/governance`
- `/memory`
- `/memory/$type`

### 6.2 真实空态页面

- `/knowledge`
- `/graph`

这两个页面不展示 mock 内容，只说明当前未接入真实写入链路。

### 6.3 Codex 数据治理页

`/governance/codex` 当前已经迁移为数据库任务驱动页面，不再按需动态加载 `codex-history.generated.ts`。

当前读取：

- `GET /api/governance/tasks?source=codex`
- `GET /api/governance/tasks/:id`
- `GET /api/governance/tasks/:id/records`
- `GET /api/governance/tasks/:id/candidates`
- `GET /api/governance/candidates/:id`

约束：

- 原始数据弹窗必须读取当前任务关联的 `sensory_records`。
- 候选状态必须落库到 `governance_candidates`。
- 引用源头必须落库到 `governance_candidate_sources`。
- 导航红点、工作台、设置、Codex 接入页、治理首页不再读取 generated snapshot。
- 公共治理算法库不得静态 import `codex-history.generated.ts`。

## 7. 当前未实现能力的技术状态

| 能力               | 当前处理                                                       |
| ------------------ | -------------------------------------------------------------- |
| 真实 AI Provider   | 未接入；设置页可保存模型配置草案；候选记忆仍为本地自动合并规则 |
| OpenAI/Ollama 配置 | 前端配置草案已展示并可本地保存；后端 Provider 调用未接入       |
| 文档连接器         | 未接入；知识库为空态                                           |
| 知识检索           | 未接入；无搜索中心                                             |
| pgvector 向量召回  | 数据库扩展已启用，业务检索未接入                               |
| 知识图谱生成       | 表预留，页面为空态                                             |
| 项目空间           | 当前无路由、无页面                                             |
| mem0 写入          | 不接入、不配置、不显示同步状态                                 |

## 8. 本轮代码走查后的调整

2026-07-12 调整：

- 删除 `src/lib/demo-data.ts`。
- 工作台改为读取 `/api/connectors/status` 和 `/api/memory/cards`。
- 导航红点改为读取真实待治理数量。
- 数据治理首页移除 mock 观察台、mock 记忆质量治理、mock 图谱治理。
- 个人知识库改为真实空态。
- 知识图谱改为真实空态。
- Codex 接入页改为读取 DB 统计和最近 `sensory_records`，不再展示 generated snapshot 全量线程。
- 设置页改为两级结构：首页包含“连接器”和“模型配置”；连接器进入卡片列表，点击卡片查看详情；模型配置进入 Provider 卡片列表，点击卡片查看详情并保存本地配置草案。
- `getConnectorStatus` 增加 `threadCount` 和 `rawTypes`。
- `getConnectorStatus` 增加 `connectorId`、`connectorName`、`originLabel`、`readScope`、`syncMode` 和 `storageTable`。
- 新增 `getDataSourceOrigins` 与 `/api/data-sources/origins`，用于数据接入页、Codex 接入页或治理任务详情查看所有数据源头；设置页只保留连接器配置入口。
- `server-db.ts` 收紧 Postgres transaction 和 JSON 类型。
- 根页面 metadata 从 Lovable 默认值改为 link。
- `src/lib/codex-governance.ts` 与 generated snapshot 解耦，并瘦身为 `rules_v1` 候选生成库。
- 新增 `governance_tasks`、`governance_task_records`、`governance_candidates`、`governance_candidate_sources`。
- `/governance/codex` 改为读取通用治理任务 API。
- 移除旧 `/api/governance/codex/complete` 完成入口，新流程使用 `/api/governance/tasks/:id/complete`。
- schema 初始化增加进程内 promise 锁，避免多个接口同时首次初始化 pgvector 时产生类型创建竞态。

## 9. 运行方式

Docker 稳定启动：

```bash
npm run stable:up
```

本地服务端口：

```text
http://127.0.0.1:41737
```

Postgres 端口：

```text
127.0.0.1:55437
```

主要环境变量：

```text
DATABASE_URL=postgres://link:link@postgres:5432/link
CODEX_HOME=/codex
OPENAI_API_KEY=
CODEX_AI_API_KEY=
```

### 9.1 AI 数据治理增量（2026-07-13）

- 新增 `ai_provider_configs`，保存当前 Provider、Base URL、模型、API Key 环境变量引用和治理提示词。
- 新增 `/api/ai/providers`、`/api/ai/providers/:provider/test` 和 `/api/governance/tasks/:id/generate`。
- AI Runner 从 `governance_task_records -> sensory_records` 分批读取全部任务数据，第一轮生成候选，第二轮按记忆类型去重合并。
- 结果写入 `governance_candidates`，引用写入 `governance_candidate_sources`；模型返回的虚假来源 ID 会被校验丢弃。
- 执行状态写入 `governance_tasks.metadata.aiGeneration`。失败不删除原始数据，任务可重试。
- 新任务默认 `generation_version = ai_v1`；`rules_v1` 仅保留历史兼容。
- 当用户选择 Codex 而非本地模型时，当前采用宿主机 Codex CLI Worker：Codex 只读分析任务关联的完整 `sensory_records`，按 JSON Schema 输出候选，再由 `scripts/import-codex-governance-result.mjs` 校验来源并事务写回。Docker 不持有 Codex 认证信息。

## 10. 验证清单

每次调整后至少验证：

- `npx tsc --noEmit`
- `npm run lint`
- `npm run build`
- `npm run stable:up`
- `/api/connectors/status`
- `/api/sensory-records?source=codex&limit=1`
- `/api/memory/cards`
- `/`
- `/settings`
- `/codex`
- `/governance`
- `/governance/codex`
- `/memory`
- `/knowledge`
- `/graph`
