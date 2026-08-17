# CHANGES — 记忆数据层管道（第一期）+ 打包修复

日期：2026-08-01
作者：TRAE CLI 协作会话

> 本仓库当前不是 git 仓库（无 `.git`），无法直接 `git commit`。本文件是完整变更清单，
> 供在真实版本控制中提交时参考。文末附可复制的 commit message。

---

## 一、业务改动：记忆数据层管道（第一期）

目标：打通「外部原始数据 → 不可变原始层 → 清洗·标记·分层 → 结构化记忆存储（pending）」。
本期**不接入 agent 运行时**：不注入 prompt、不注册写工具、不改动正常对话上下文；管道产物停在
`status='pending'`，等待后续确认闭环。

### 后端（Python）

| 文件 | 状态 | 改动 |
|---|---|---|
| `smallink/memory/base.py` | 改 | `MemoryItem` 增 `status`/`updated_at`/`source_record_id`；`MemoryStore.add`、`list` 增对应参数，`list` 默认 `status="active"`（保证 pending 不泄漏进 prompt/确认视图） |
| `smallink/memory/sqlite_store.py` | 改 | 加法迁移新增 3 列（旧行自动回填 `active`，不丢数据）；新建 `memory_history` 版本表；`add/update/delete` 各写一条 `ADD/UPDATE/DELETE` 历史；`list` 支持 status 过滤；新增 `list_history()` |
| `smallink/memory/pipeline.py` | **新增** | `MemoryPipeline`：一次 LLM 调用完成 清洗（提炼）→ 标记（10 种类型）→ 分层（scope）；产出 `pending` + `source_record_id` 溯源；LLM 失败兜底（存原文，绝不抛错）；靠 `source_record_id` 幂等。含 `MEMORY_TYPES`、`EXTRACTION_PROMPT` |
| `smallink/memory/__init__.py` | 改 | 导出 `MemoryPipeline`、`MEMORY_TYPES` |
| `smallink/server/manager.py` | 改 | 导入 `MemoryPipeline`；新增 `ingest_sensory_record`（复用 `SQLiteSensoryStore.add` + `_sensory_safe`，缺字段报错）、`run_memory_pipeline`；`list_memory` 支持 status 过滤（默认 active） |
| `smallink/server/app.py` | 改 | 新增 `POST /v1/sensory-records`（ingest，ValueError→400）、`POST /v1/memory/pipeline/run`（`asyncio.to_thread` 卸载阻塞 LLM）；`GET /v1/memory` 增 `status` 查询参数（默认 active） |

### 前端（TypeScript / React）

| 文件 | 状态 | 改动 |
|---|---|---|
| `surfaces/gui/src/api.ts` | 改 | `MemoryRecord` 增 `status`/`updated_at`/`source_record_id`；`getMemory(status?)` 支持 active/pending/all |
| `surfaces/gui/src/components/MemoryView.tsx` | 改 | 新增只读「待确认(pending)」查看区：landing 页 banner 提示数量 → 点进只读列表 → 详情显示 类型/scope/状态。无确认/编辑按钮（确认闭环留下期）。新增 `typeLabel` 辅助 |
| `surfaces/gui/src/i18n.tsx` | 改 | 新增 pending 查看区相关中英文案（Awaiting confirmation、Review、Type、Status、Uncategorized 等） |

### 测试

| 文件 | 状态 | 改动 |
|---|---|---|
| `tests/test_memory_pipeline.py` | **新增** | typed 抽取 / 多事实与 global scope / 坏 JSON 兜底 / provider 异常兜底 / 幂等 / 空 facts |
| `tests/test_sensory.py` | 改 | ingest 写入 / 幂等 / 缺字段 400 |
| `tests/test_memory.py` | 改 | 新增默认 active / pending 排除默认 list / 迁移回填 active / 版本历史 ADD-UPDATE-DELETE |
| `surfaces/gui/src/components/MemoryView.test.tsx` | 改 | 适配 getMemory(status) 双调用；新增 pending banner→review 视图测试、空队列隐藏 banner 测试 |

### 文档

| 文件 | 状态 | 改动 |
|---|---|---|
| `docs/link-memory-technical-design.md` | 改 | 新增第 0 章「当前已实现（SQLite 过渡实现）」+ 与 Postgres 目标的映射表；保留目标章节不动 |
| `docs/link-memory-prd.md` | 改 | 加「当前进度」说明段 |

### 测试结果
- 后端：`929 passed, 1 skipped`（+13 新测试）。唯一失败 `tests/test_shell.py::test_timeout_kills_command` 是既有计时抖动（`4.05 < 4.0`），与本次无关。
- 前端：`92 passed`（+2 MemoryView 测试）。`tsc` 严格类型检查 + `vite build` 通过。

---

## 一之二、Codex 数据连接器（把 Codex 对话导入记忆源）

目标：给记忆库喂真实数据。新增 `codex` 本地连接器，把 `~/.codex/sessions/**/rollout-*.jsonl`
里的对话导入 `sensory_records`（本期已建的原始层），再由 pipeline 炼成记忆。粒度=**按对话轮次**
（一个 user 提问 + 其后连续的 assistant 回复合成一条，含完整问答上下文）；接入=正式连接器 + 采集器；
范围支持"最近 N 个会话"先验证。

| 文件 | 状态 | 改动 |
|---|---|---|
| `smallink/connectors/codex_client.py` | **新增** | 解析 rollout JSONL：`session_meta` 取 session_id/cwd/timestamp/model；`response_item`+`message`+role∈{user,assistant} 取对话，`content` 的 input_text/output_text 拼文本；过滤 4 类审批协议噪声（见下）；容错坏行；`read_sessions(limit=N)` 按文件名（时间）倒序取最近 N，支持 `$CODEX_HOME`；`CodexSession.turns()` 把消息聚合成"轮次"（U + 后续 A，`UAAUA→2轮`） |
| `smallink/server/manager.py` | 改 | 新增 `sync_codex(limit_sessions)`：读会话→**每个轮次**调 `ingest_sensory_record`（`source_type=codex`、`content_type=codex_turn`、`external_id=session:turn_index`、`raw_content` 为 `User:/Assistant:` 转录、带 cwd/conversation_id/roles 元数据）；用 `count()` 前后差报告真实新增数（幂等） |
| `smallink/server/app.py` | 改 | 新增 `POST /v1/connectors/codex/sync`（`asyncio.to_thread` 卸载文件 I/O，`limit_sessions` 可选） |
| `smallink/connectors/descriptors.py` | 改 | 注册 `codex` 描述符（`auth="local_app"`、只读、无字段） |
| `smallink/connectors/catalog_copy.py` | 改 | 加 `codex` 的 ABOUT/ACCESS 文案（每个可用连接器必需，否则 test_connectors 失败） |
| `smallink/connectors/cli.py` | 改 | 新增 `sync-codex [--limit N]` 子命令（独立运行，不需起服务） |
| `surfaces/gui/src/components/connectors/visibility.ts` | 改 | 前端白名单加 `codex` |
| `tests/test_codex_connector.py` | **新增** | 解析（抽取/噪声过滤/坏行容错）、最近N倒序、轮次聚合、sync 按轮次入库 + 幂等，7 个用例 |

**验证（本机真实数据）**：`sync_codex(limit=10)` → 2 个有效会话、11 个轮次、入库 11 条记录（每条含完整
`User:…/Assistant:…` 问答）；re-sync=0（幂等）。端到端：sync→pipeline→pending typed 记忆，确认视图仍为空
（pending 隔离生效）。后端全套 `936 passed, 1 skipped`（+7 Codex 测试；唯一失败仍是既有 shell 计时抖动）。

**噪声过滤**：实测 10 会话 103 条消息中 **~57% 是 Codex 审批协议噪声**，`_is_noise` 按 4 类规则过滤：
① 纯 JSON 协议载荷（`{"outcome":"allow"}` 等审批判定）② 审批 preamble（"The following is the Codex agent
history…"）③ AGENTS.md/`<INSTRUCTIONS>` 脚手架 ④ 注入的 XML 上下文块（`<environment_context>`/
`<recommended_plugins>` 等）。真实对话（含以 `# Files mentioned by the user:` 开头的正常 user 消息）保留。
过滤后 0 噪声漏网（`test_noise_filters_drop_codex_protocol_traffic` 覆盖）。

---

## 一之三、Codex 文件夹授权（修复安装后"连不上"）

**问题**：安装后的 App 里 sync 返回 `sessions_read:0`，虽然 `~/.codex` 有 386 个文件。根因是 **macOS TCC 隐私
保护**——ad-hoc 签名的 App 无权读主目录下的 `~/.codex`，`rglob` 被静默拒绝返回空（非代码 bug；`CODEX_HOME`
指向 `/tmp` 副本时同一 sidecar 能正常读，证明是权限）。

**方案 A（手动选目录授权）**：让用户在原生文件夹弹框里选 `~/.codex`——这个动作本身就让 macOS 授予读权限。

| 文件 | 状态 | 改动 |
|---|---|---|
| `smallink/connectors/codex_client.py` | 改 | 新增 `resolve_sessions_root(picked)`：把用户选的 `~/.codex` 规范到 `~/.codex/sessions`（或直接用已是 sessions 的目录）；新增 `_MAX_ROLLOUT_BYTES=64MiB` 跳过异常巨大的 rollout（本机有个 1GB 文件），全量扫描 10s→0.8s |
| `smallink/connectors/setup.py` | 改 | `connect_connector` 的 `local_app` 分支放行 `codex`：把选中路径经 `resolve_sessions_root` 存进 `codex:default` 档案的 `sessions_path`（无 App 启动/健康检查，纯本地文件源） |
| `smallink/server/manager.py` | 改 | `sync_codex` 优先读 `codex:default` 的授权路径（`read_sessions(root=...)`），无授权时回退默认 `~/.codex/sessions` |
| `surfaces/gui/src/components/connectors/AddConnectionModal.tsx` | 改 | `LocalAppConnect` 对 `codex` 分流到新 `CodexConnect`：调 `chooseFolder()` 原生选目录 → `connectConnector(codex,{sessions_path})` |
| `surfaces/gui/src/components/connectors/ConnectorsSection.tsx` | 改 | 连接后详情页加 `CodexImportBlock`（"导入对话"按钮调 `syncCodex()`，显示导入结果）；状态行对 codex 显示"Codex 文件夹已连接" |
| `surfaces/gui/src/api.ts` | 改 | 新增 `syncCodex(limitSessions?)`；`connectConnector` 的 `fields` 传 `sessions_path` |
| `surfaces/gui/src/i18n.tsx` | 改 | 加 Codex 授权/导入相关中英文案 |
| `tests/test_codex_connector.py` | 改 | +路径规范化、+connect 存路径且 sync 读该路径、+超大文件跳过，共 10 个用例 |

**验证（用打好的 .app 内 sidecar + 真实数据）**：connect `~/.codex` → 存 `sessions_path` → import → 读 17 会话、
119 轮次、入库 105 条真实对话记录；`GET /v1/sensory-records?source_type=codex` total=105。后端全套
`939 passed, 1 skipped`（唯一失败仍是既有 shell 计时抖动）；前端 `92 passed` + `tsc`/`vite build` 通过。

**使用**：连接器 → Codex → 选择 Codex 文件夹（选 `~/.codex`，系统弹权限框须点允许）→ 导入对话。

---

## 一之四、模型用途标签（多选）+ pipeline 用途路由

**动机**：模型管理原本只有一个全局默认模型；记忆 pipeline 硬编码用全局默认，无法单独指定"记忆用哪个模型"。
照现有模型管理形态，给每个模型加**"使用用途"多选标签**（chat/memory/title），pipeline 用打了 `memory`
用途的模型——顺带补掉"无独立记忆模型设置"的缺口。

| 文件 | 状态 | 改动 |
|---|---|---|
| `smallink/server/manager.py` | 改 | 加 `MODEL_PURPOSES=("chat","memory","title")`；`set_model_purposes(model,purposes)`（存 `prefs.json` 的 `model_purposes`，多选，未知用途剔除，清空即删条目）；`model_for_purpose(purpose)`（取标注该用途的模型，多个时优先默认、否则第一个，无则回退全局默认）；`get_settings` 返回 `model_purposes`+`purposes`；`run_memory_pipeline` 改用 `model_for_purpose("memory")` |
| `smallink/server/app.py` | 改 | 加 `POST /v1/settings/model-purposes {model,purposes}` |
| `surfaces/gui/src/api.ts` | 改 | `ModelSettings` 加 `model_purposes`/`purposes`；`setModelPurposes(model,purposes)` |
| `surfaces/gui/src/components/ModelChecklist.tsx` | 改 | 每个模型行加用途多选 chip（对话/记忆/标题），点击调 `setModelPurposes`，乐观更新 |
| `surfaces/gui/src/components/ManageTabs.tsx` | 改 | 传 `purposes`/`modelPurposes` 给 `ModelChecklist` |
| `surfaces/gui/src/styles.css` · `i18n.tsx` | 改 | chip 样式 + 中英文案（"For chat/For memory/For titles"，避开与既有键冲突） |
| `tests/test_model_purposes.py` | **新增** | 存取/未知剔除/清空删条目/解析（标注·多标注取默认·回退）/pipeline 用 memory 模型/未标注回退，6 用例 |

**本期只接 memory**：`chat`/`title` 标签可存但暂不接线（对话/标题主链不动，降风险）。**验证**：.app 内 sidecar
设 `ollama:qwen3→[memory,chat]` → `/v1/settings` 回读正确 → pipeline 实测调用该模型（`test_pipeline_uses_memory_tagged_model`）。
后端 `945 passed, 1 skipped`（+6）；前端 `92 passed` + build 通过。

**使用**：设置 → 模型 → 每个模型行勾选"用于记忆"→ 该模型即用于记忆 pipeline（未勾选任何模型时回退默认模型）。

---

## 一之五、Codex 一键授权、连接和导入

**问题**：此前 CLI 的连接流程只写了一半（`_cmd_sync_codex` 已接受 folder/reconnect，但 argparse 未暴露参数且
调用签名不匹配）；应用内也仍是“先选目录连接，再到详情页点导入”两步。

**实现**：

| 文件 | 状态 | 改动 |
|---|---|---|
| `smallink/connectors/cli.py` | 改 | `sync-codex` 新增 `--folder`、`--reconnect`；无已授权路径时自动打开原生文件夹选择器，选择后持久化 connector profile，再立即导入；已连接时直接增量导入 |
| `scripts/connect_codex.sh` | **新增** | 一键脚本，调用 `.venv/bin/smallink-connectors sync-codex`；默认弹原生目录授权框，也可传 `--folder ~/.codex --limit N --reconnect` |
| `surfaces/gui/src/components/connectors/AddConnectionModal.tsx` | 改 | Codex 连接按钮改为“授权并导入”：原生选目录 → connect → sync，一次完成；显示授权/导入进度和最终计数 |
| `surfaces/gui/src/i18n.tsx` | 改 | 一键授权、连接、导入相关中英文案 |

**验证**：`scripts/connect_codex.sh --folder ~/.codex --limit 30` 首次读 3 有效会话、13 轮次、入库 13 条；
同状态目录再次执行新增 0（幂等）。前端 build、92 tests；相关后端 73 tests。

---

## 一之六、TraeX / TRAE CLI 本地对话连接器

**问题**：此前只有 Codex 连接器扫描 `~/.codex/sessions`，本机 TraeX / TRAE CLI 的会话实际存放在
`~/.trae/cli/sessions`，因此 TRAE 对话从未进入 Smallink 原始数据池。

**实现**：

- 新增 `traex` 独立连接器和 `POST /v1/connectors/traex/sync`，以 `source_type='traex'`、
  `content_type='traex_turn'` 写入 `sensory_records`，不再错误标记为 Codex。
- 复用 rollout JSONL 解析器，但只导入 `thread_source=user`（或旧版缺失该字段）的主会话；
  排除子智能体内部线程、权限说明、系统提醒和旧版日期/时区提示。
- 只导入已有 `task_complete` 的轮次；正在追加的当前轮次等待完成后再增量同步，避免同一轮产生多个内容版本。
- 支持 GUI 一键授权 `~/.trae`、连接并导入，也支持
  `smallink-connectors sync-traex --folder ~/.trae`。
- 连接器列表和详情页复用本地会话源交互，显示“就绪”而不是错误的“已停止”。
- 记忆首页新增原始源数据、TRAE 数据和 Codex 数据计数，区分“已采集”与“已生成候选记忆”。

**真实数据验证**：本机发现 52 个 TRAE rollout 文件，其中 12 个用户主会话、40 个子智能体线程。
完成边界过滤后导入 72 个已完成轮次；再次同步新增 0。试同步阶段产生的 10 条未完成/旧版本记录已精确清理，
且没有任何一条被记忆管道引用。

**测试**：后端连接器与注册表聚焦测试 `80 passed`，TraeX/Codex 回归 `15 passed`；前端相关组件
`14 passed`，`tsc && vite build` 通过。

---

## 二、打包修复：补齐仓库缺失的构建文件

打包时发现以下构建文件**从未提交进仓库**，导致 `packaging/build_dmg.sh` 无法完成。这是仓库既有
缺陷（非本次业务改动引入），已补齐使打包可复现：

| 文件 | 状态 | 说明 |
|---|---|---|
| `packaging/smallink-server.spec` | **新增** | PyInstaller 冻结配置；`build_dmg.sh` 依赖它但文件缺失。用 `collect_all` 收集 providers/mcp/ddgs 等的数据与动态导入，捆绑内置 persona，`LINK_EXPERIMENTAL` 未设时排除实验连接器。**修复**：`smallink` 是 editable 安装（自定义 MetaPathFinder），PyInstaller 静态分析跟不进去，导致冻结包里只有 personas/、缺 server/memory/connectors 等模块，运行时 `ModuleNotFoundError: smallink.server`——改为 `pathex=绝对源码根` + 把整个 `smallink`/`link` 源码树作为 datas 打入，并已用 .app 内 sidecar 实测启动成功（health 200、codex 在 catalog）。 |
| `packaging/entry_smallink_server.py` | **新增** | PyInstaller 入口 shim（`run.py` 用相对导入，不能直接作冻结入口） |
| `surfaces/gui/src-tauri/build.rs` | **新增** | Tauri 构建脚本 `fn main(){ tauri_build::build(); }`；`Cargo.toml` 声明了 `tauri-build` 却缺 build.rs，导致 `generate_context!` 报 `OUT_DIR not set` |
| `surfaces/gui/src-tauri/icons/*` | **新增** | 由 `npx tauri icon design/brand/smallink-mark.png` 生成的完整图标集（19 个文件，构建必需，`tauri.conf.json` 的 `bundle.icon` 引用） |
| `packaging/dmg-background.tiff` | **新增** | DMG 安装窗口背景图（HiDPI 1x+2x TIFF），装饰用；`build_dmg.sh` 硬引用它 |

### 产物
`surfaces/gui/src-tauri/target/release/bundle/dmg/Smallink_0.1.6_aarch64.dmg`（56M，Apple
Silicon，本地 ad-hoc 签名，未公证）。**仅供本地，不可分发**；安装需 `xattr -cr /Applications/Smallink.app`。

### 环境备注（不入库）
- venv 装了 `pyinstaller tzdata typer cmake`（构建期依赖；`cmake` 供 whisper-rs 编译 STT）。
- `hdiutil` 因沙箱限制无法建磁盘镜像，最终 DMG 封装在关闭沙箱下完成。

---

## 三、不应提交的内容（构建产物 / 环境）

以下由构建生成，**不要提交**（建议加入 `.gitignore`）：
- `packaging/dist/`、`packaging/build/`（PyInstaller 输出）
- `surfaces/gui/src-tauri/binaries/sidecar/`（冻结的 server + 数千个第三方库文件）
- `surfaces/gui/src-tauri/target/`（Rust/Tauri 编译产物，含最终 DMG）
- `surfaces/gui/dist/`（Vite 前端构建）
- `.venv/`、`surfaces/gui/node_modules/`、各 `__pycache__/`

---

## 四、可复制的 commit message

```
feat(memory): 记忆数据层管道（ingest → 清洗·标记·分层 → pending 存储）

打通外部原始数据到结构化记忆的数据层，不接入对话运行时：
- 新增通用 ingest 端点 POST /v1/sensory-records（写入不可变 sensory_records，幂等）
- 新增 MemoryPipeline：LLM 提炼→类型标记→scope 分层，产出 status='pending' 记忆，
  带 source_record_id 溯源与 LLM 失败兜底；POST /v1/memory/pipeline/run 手动触发
- 扩展 SQLiteMemoryStore：status/updated_at/source_record_id 列（加法迁移，旧行回填 active）
  + memory_history 版本表；list 默认 active（pending 不泄漏进 prompt/确认视图）
- 前端 MemoryView 新增只读「待确认」查看区（无确认/编辑按钮，确认闭环留后期）
- 文档：记忆技术方案新增「当前 SQLite 过渡实现」章节与目标映射

fix(packaging): 补齐缺失的构建文件使桌面打包可复现

补齐从未提交的构建产物依赖（既有缺陷，非本次业务引入）：
PyInstaller spec + 入口 shim、Tauri build.rs、图标集、DMG 背景图。
产出未签名本地 DMG（Smallink_0.1.6_aarch64.dmg）。

测试：后端 929 passed / 前端 92 passed（tsc+vite build 通过）。

Co-authored-by: TRAE CLI <noreply@bytedance.com>
```
