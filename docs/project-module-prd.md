# 项目模块需求文档

文档版本：1.0
创建日期：2026-08-08
状态：草案
关联文档：[产品 PRD 第 10 章](./link-product-prd.md)

## 1. 背景与目标

### 1.1 现状

当前 Smallink 的"项目"概念仅靠 session 上的 `workspace` 字段（文件系统路径）隐式实现：
- 没有独立的 Project 数据实体
- 没有项目级别的配置（默认模型、智能体、预算等）
- 侧边栏按路径分组但无法管理项目本身
- 用户无法在项目维度创建、归档、删除

### 1.2 目标

建设一个轻量级 Project 模块，实现：
1. 项目作为一等实体存在，拥有名称、图标、关联目录和配置
2. 侧边栏"项目"区域展示所有项目，可折叠展开查看项目下的会话
3. 选择项目后，新建会话自动继承项目上下文（目录、配置）
4. 项目内会话在输入区域明确显示当前项目标识
5. 支持项目的增删改和归档

### 1.3 设计原则

- 项目是组织范围，不是数据副本（与 PRD 第 10 章一致）
- 向下兼容：已有 session 的 workspace 字段自动映射为项目
- 最小侵入：复用现有 workspace 信任、FolderGate 等机制
- 增量交付：先做核心 CRUD 和侧边栏，后续再扩展关联记忆/知识/产物

---

## 2. 核心概念

### 2.1 Project 对象

| 字段 | 类型 | 说明 |
|------|------|------|
| project_id | TEXT (UUID) | 主键 |
| name | TEXT | 项目显示名（默认取文件夹 basename） |
| icon | TEXT | 项目图标（emoji 或图标标识，可选） |
| workspace_path | TEXT | 关联的文件系统目录（唯一约束） |
| description | TEXT | 项目说明（可选） |
| status | TEXT | active / paused / completed / archived |
| default_agent | TEXT | 默认智能体（可选，继承全局） |
| default_model | TEXT | 默认模型（可选，继承全局） |
| pinned | INTEGER | 是否置顶（侧边栏排序） |
| sort_order | INTEGER | 手动排序权重 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 最近活动时间 |

### 2.2 与 Session 的关系

- Session 表新增 `project_id TEXT` 外键字段（可选）
- 一个 Project 下有多个 Session（1:N）
- Session 的 `workspace` 字段保留，与 project 的 `workspace_path` 保持一致
- 无项目的会话仍正常存在于"最近"区域

### 2.3 迁移策略

现有 session 按 `workspace` 字段分组，启动时自动为每个 unique workspace 创建对应 Project 记录，`project_id` 回填到 session 上。用户无感知。

---

## 3. 功能需求

### 3.1 侧边栏 — 项目区域

**布局结构：**
```
┌─────────────────────────┐
│ 项目                     │
│ ┌─ 📁 视频         ··· ✎│  <- 项目行：图标 + 名称 + 操作菜单 + 新建会话
│ │   制定半导体调研前置清单   │  <- 项目下的会话列表（折叠/展开）
│ │   读取文档并删减实际内容   │
│ │   学习这个技能            │
│ ├─ 📁 Smallink       ··· ✎│
│ ├─ 📁 MineM          ··· ✎│
│ └─ 📁 VOC            ··· ✎│
│                          │
│ 最近                     │
│   调研绫家与斐萃品牌动态     │
│   生成短视频产品框架 (2)    │
│   ...                    │
└─────────────────────────┘
```

**交互规则：**

| 操作 | 行为 |
|------|------|
| 点击项目名 | 展开/折叠该项目的会话列表 |
| 点击项目右侧 `✎` | 在项目上下文中新建会话 |
| 点击项目右侧 `···` | 打开项目操作菜单（重命名、设置、归档、删除） |
| 拖拽项目行 | 手动调整项目排序 |
| 点击项目下某会话 | 切换到该会话 |
| 项目会话列表超过 5 条 | 默认显示最新 5 条 + "展开更多" |

**新建项目：**
- 侧边栏"项目"标题旁显示 `+` 按钮
- 点击后触发原生文件夹选择器（复用 FolderGate / `/v1/workspaces/pick`）
- 选择目录后创建 Project 记录
- 项目名默认取目录 basename，支持即时编辑

### 3.2 项目上下文对话

**进入项目：**
- 用户点击项目右侧 `✎` 新建会话，或点击项目下已有会话
- 进入会话后，输入框上方显示项目标识徽章（如截图所示的 `📁 MineM` 标签）

**上下文继承：**
- 在项目内新建会话时自动设置：
  - `workspace` = 项目的 `workspace_path`
  - `project_id` = 项目 ID
  - `agent` = 项目的 `default_agent`（如配置）
  - `model` = 项目的 `default_model`（如配置）
- 跳过 FolderGate（目录已确定）

**项目标识显示：**
- 输入区域顶部展示当前项目名（芯片样式）
- 点击项目芯片可快速切换到其他项目或移除项目关联

### 3.3 项目管理

**项目设置面板（从 `···` 菜单进入）：**
- 项目名称编辑
- 项目图标选择
- 项目说明编辑
- 关联目录展示（只读，可更换）
- 默认智能体选择
- 默认模型选择
- 项目状态切换（active / paused / completed / archived）

**项目删除：**
- 删除只移除 Project 记录和关联关系
- 项目下的会话转为"无项目"状态，保留在"最近"区域
- 二次确认对话框，明确说明不会删除文件或会话内容

**项目归档：**
- 归档项目从侧边栏主区域隐藏
- 可在设置/筛选中查看已归档项目
- 归档项目下的会话仍可通过搜索找到

### 3.4 快捷操作

| 快捷方式 | 行为 |
|----------|------|
| Cmd+Shift+P | 打开项目切换器（类似 VS Code 的 Quick Open） |
| 在项目内 Cmd+N | 在当前项目下新建会话 |
| 搜索 `/project:name` | 按项目筛选会话 |

---

## 4. API 设计

### 4.1 REST Endpoints

| Method | Path | 说明 |
|--------|------|------|
| GET | `/v1/projects` | 列出所有项目（支持 ?status=active 筛选） |
| POST | `/v1/projects` | 创建项目 |
| GET | `/v1/projects/{id}` | 获取单个项目详情 |
| PATCH | `/v1/projects/{id}` | 更新项目（名称、图标、配置、状态） |
| DELETE | `/v1/projects/{id}` | 删除项目（会话转为无项目） |
| GET | `/v1/projects/{id}/sessions` | 获取项目下的会话列表 |
| POST | `/v1/projects/{id}/sessions` | 在项目下创建新会话 |

### 4.2 请求/响应示例

**POST `/v1/projects`**
```json
{
  "workspace_path": "~/Documents/work/video-project",
  "name": "视频",
  "icon": "📁",
  "default_agent": "code",
  "default_model": null
}
```

**Response:**
```json
{
  "project_id": "proj_abc123",
  "name": "视频",
  "icon": "📁",
  "workspace_path": "~/Documents/work/video-project",
  "status": "active",
  "session_count": 0,
  "created_at": "2026-08-08T10:00:00Z",
  "updated_at": "2026-08-08T10:00:00Z"
}
```

**GET `/v1/projects`**
```json
{
  "projects": [
    {
      "project_id": "proj_abc123",
      "name": "视频",
      "icon": "📁",
      "workspace_path": "/Users/...",
      "status": "active",
      "session_count": 3,
      "latest_session_at": "2026-08-08T09:30:00Z",
      "pinned": false
    }
  ]
}
```

### 4.3 WebSocket Events

新增事件类型通过 `/ws/events` 推送：
- `project.created` — 新项目创建
- `project.updated` — 项目信息变更
- `project.deleted` — 项目删除
- `project.session_added` — 项目下新增会话

---

## 5. 数据库变更

### 5.1 新增 `projects` 表

```sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT DEFAULT '📁',
    workspace_path TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    default_agent TEXT,
    default_model TEXT,
    pinned INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_workspace ON projects(workspace_path);
```

### 5.2 修改 `sessions` 表

```sql
ALTER TABLE sessions ADD COLUMN project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL;
CREATE INDEX idx_sessions_project ON sessions(project_id);
```

### 5.3 数据迁移

```sql
-- 自动为已有 workspace 创建项目
INSERT INTO projects (project_id, name, workspace_path, created_at, updated_at)
SELECT
    lower(hex(randomblob(16))),
    CASE
        WHEN instr(workspace, '/') > 0
        THEN substr(workspace, length(workspace) - length(replace(workspace, '/', '')) + 1)
        ELSE workspace
    END,
    workspace,
    MIN(updated_at),
    MAX(updated_at)
FROM sessions
WHERE workspace IS NOT NULL AND workspace != ''
GROUP BY workspace;

-- 回填 project_id
UPDATE sessions SET project_id = (
    SELECT project_id FROM projects WHERE projects.workspace_path = sessions.workspace
) WHERE workspace IS NOT NULL AND workspace != '';
```

---

## 6. 前端组件设计

### 6.1 新增组件

| 组件 | 职责 |
|------|------|
| `ProjectSection.tsx` | 侧边栏项目区域（项目列表 + 折叠会话） |
| `ProjectRow.tsx` | 单个项目行（图标、名称、操作按钮） |
| `ProjectBadge.tsx` | 输入区域上方的项目标识芯片 |
| `ProjectSettings.tsx` | 项目设置面板 |
| `ProjectSwitcher.tsx` | Cmd+Shift+P 快速切换弹窗 |
| `CreateProjectDialog.tsx` | 新建项目对话框（选择目录 + 命名） |

### 6.2 状态管理

在 `App.tsx` 中新增：
```typescript
const [projects, setProjects] = useState<Project[]>([]);
const [activeProject, setActiveProject] = useState<Project | null>(null);
```

新增类型（`types.ts`）：
```typescript
interface Project {
  project_id: string;
  name: string;
  icon: string;
  workspace_path: string;
  description: string;
  status: 'active' | 'paused' | 'completed' | 'archived';
  default_agent?: string;
  default_model?: string;
  pinned: boolean;
  sort_order: number;
  session_count: number;
  latest_session_at?: string;
  created_at: string;
  updated_at: string;
}
```

### 6.3 现有组件修改

| 组件 | 修改内容 |
|------|----------|
| `Sidebar.tsx` | 顶部增加 ProjectSection，替代原有的 workspace 分组逻辑 |
| `App.tsx` | 新增 projects 状态、startNewSession 支持 project 参数 |
| `api.ts` | 新增 project CRUD API 调用函数 |
| 输入区域 | 顶部增加 ProjectBadge 显示当前项目 |

---

## 7. 实现阶段

### Phase 1：核心骨架（本次）

- [ ] 后端：projects 表 + CRUD API + 数据迁移
- [ ] 后端：session 创建时支持 project_id
- [ ] 前端：ProjectSection 侧边栏组件
- [ ] 前端：ProjectBadge 输入区域标识
- [ ] 前端：CreateProjectDialog（选择目录 + 命名）
- [ ] 前端：项目内新建会话自动继承上下文

### Phase 2：管理与体验增强

- [ ] 项目设置面板（配置默认智能体/模型）
- [ ] 项目归档和状态管理
- [ ] Cmd+Shift+P 项目快速切换
- [ ] 项目排序拖拽
- [ ] WebSocket 事件推送

### Phase 3：深度集成（对齐 PRD 第 10 章）

- [ ] 项目关联记忆和知识
- [ ] 项目关联自动化
- [ ] 项目关联产物
- [ ] 项目时间线
- [ ] 项目首页仪表板

---

## 8. 验收标准

1. 用户可以从侧边栏创建新项目（选择文件夹 -> 自动命名 -> 出现在项目列表）
2. 已有会话按 workspace 自动归入对应项目（迁移无感知）
3. 点击项目展开可查看该项目下的会话列表
4. 在项目中新建会话时，跳过目录选择，自动继承项目路径
5. 会话输入区域显示当前项目标识
6. 删除项目不会删除会话或文件
7. 无项目会话仍正常显示在"最近"区域
8. 项目支持重命名和图标修改

---

## 9. 非目标（本次不做）

- 项目关联记忆/知识/产物（Phase 3）
- 项目级别的权限和预算管理
- 多人协作项目
- 项目模板
- 项目导入/导出
