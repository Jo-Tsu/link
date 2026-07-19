import { invoke } from "@tauri-apps/api/core";
import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  Activity,
  Cable,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Cloud,
  ExternalLink,
  FileClock,
  FolderKey,
  Laptop,
  LoaderCircle,
  LogOut,
  Play,
  RefreshCw,
  Settings,
  Terminal,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import "./App.css";

type SyncSummary = {
  selected: number;
  uploaded: number;
  inserted: number;
  updated: number;
  completedAt: string;
  error: string;
};

type AgentState = {
  paired: boolean;
  platformUrl: string;
  agentId: string;
  displayName: string;
  status: "unpaired" | "online" | "offline";
  version: string;
  lastSeenAt: string;
  codexAvailable: boolean;
  codexAuthorized: boolean;
  codexPath: string;
  syncing: boolean;
  queuedBatches: number;
  lastSync?: SyncSummary;
};

type Page = "device" | "connectors" | "sync" | "settings";

const emptyState: AgentState = {
  paired: false,
  platformUrl: "",
  agentId: "",
  displayName: "",
  status: "unpaired",
  version: "0.2.0",
  lastSeenAt: "",
  codexAvailable: false,
  codexAuthorized: false,
  codexPath: "",
  syncing: false,
  queuedBatches: 0,
};

const pages: Array<{ id: Page; label: string; icon: typeof Laptop }> = [
  { id: "device", label: "设备", icon: Laptop },
  { id: "connectors", label: "连接器", icon: Cable },
  { id: "sync", label: "同步记录", icon: FileClock },
  { id: "settings", label: "设置", icon: Settings },
];

function App() {
  const [state, setState] = useState<AgentState>(emptyState);
  const [page, setPage] = useState<Page>("device");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [autostart, setAutostart] = useState(false);

  const loadState = useCallback(async () => {
    try {
      const next = await invoke<AgentState>("get_agent_state");
      setState(next);
      setError("");
      if (next.paired) {
        try {
          setState(await invoke<AgentState>("heartbeat"));
        } catch {
          setState((current) => ({ ...current, status: "offline" }));
        }
      }
    } catch (loadError) {
      setError(toMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadState();
    void isEnabled()
      .then(setAutostart)
      .catch(() => setAutostart(false));
  }, [loadState]);

  useEffect(() => {
    if (page !== "sync") return;
    void invoke<string[]>("get_recent_logs")
      .then(setLogs)
      .catch(() => setLogs([]));
  }, [page, state.lastSync]);

  async function authorizeCodex() {
    await runAction(async () => {
      setState(await invoke<AgentState>("authorize_codex"));
      setMessage("Codex 只读范围已确认，可以开始同步。");
    });
  }

  async function syncCodex() {
    await runAction(async () => {
      setState((current) => ({ ...current, syncing: true }));
      const result = await invoke<SyncSummary>("sync_codex");
      setState((current) => ({ ...current, syncing: false, lastSync: result }));
      setMessage(`同步完成，已上传 ${result.uploaded.toLocaleString()} 条记录。`);
      await loadState();
    });
  }

  async function runAction(action: () => Promise<void>) {
    setWorking(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (actionError) {
      setError(toMessage(actionError));
      setState((current) => ({ ...current, syncing: false }));
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return (
      <div className="boot-screen">
        <LoaderCircle className="spin" />
        <span>正在启动 LinkAgent</span>
      </div>
    );
  }

  if (!state.paired) {
    return <PairingPage onPaired={setState} error={error} />;
  }

  const currentPage = pages.find((item) => item.id === page);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">L</span>
          <div>
            <strong>LinkAgent</strong>
            <span>本地连接器</span>
          </div>
        </div>
        <nav>
          {pages.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={page === item.id ? "nav-item active" : "nav-item"}
                onClick={() => setPage(item.id)}
              >
                <Icon />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-status">
          <StatusDot status={state.status} />
          <div>
            <strong>{statusLabel(state.status)}</strong>
            <span>{state.displayName || "当前设备"}</span>
          </div>
        </div>
      </aside>

      <main className="content">
        <header className="page-header">
          <div>
            <span className="eyebrow">LinkAgent</span>
            <h1>{currentPage?.label}</h1>
          </div>
          <button className="icon-button" title="刷新状态" onClick={() => void loadState()}>
            <RefreshCw />
          </button>
        </header>

        {(message || error) && (
          <div className={error ? "notice error" : "notice success"}>
            {error ? <CircleAlert /> : <CheckCircle2 />}
            {error || message}
          </div>
        )}

        {page === "device" && (
          <DevicePage state={state} onOpenPlatform={() => void openUrl(state.platformUrl)} />
        )}
        {page === "connectors" && (
          <ConnectorsPage
            state={state}
            working={working}
            onAuthorize={authorizeCodex}
            onSync={syncCodex}
          />
        )}
        {page === "sync" && <SyncPage state={state} logs={logs} />}
        {page === "settings" && (
          <SettingsPage
            state={state}
            autostart={autostart}
            onAutostart={async (enabled) => {
              await runAction(async () => {
                if (enabled) await enable();
                else await disable();
                setAutostart(await isEnabled());
              });
            }}
            onUnpair={() =>
              void runAction(async () => {
                setState(await invoke<AgentState>("unpair_agent"));
              })
            }
          />
        )}
      </main>
    </div>
  );
}

function PairingPage({
  onPaired,
  error,
}: {
  onPaired: (state: AgentState) => void;
  error: string;
}) {
  const [platformUrl, setPlatformUrl] = useState("http://127.0.0.1:41737");
  const [pairingCode, setPairingCode] = useState("");
  const [displayName, setDisplayName] = useState("我的 Mac");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(error);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      const result = await invoke<AgentState>("pair_agent", {
        platformUrl,
        pairingCode,
        displayName,
      });
      onPaired(result);
    } catch (pairError) {
      setFormError(toMessage(pairError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="pairing-shell">
      <section className="pairing-intro">
        <div className="brand large">
          <span className="brand-mark">L</span>
          <div>
            <strong>LinkAgent</strong>
            <span>让本机数据安全连接到 Link</span>
          </div>
        </div>
        <div className="pairing-points">
          <PairingPoint
            icon={FolderKey}
            title="权限留在本机"
            text="Codex 和后续连接器凭据不会上传到平台。"
          />
          <PairingPoint
            icon={Activity}
            title="后台增量同步"
            text="离线批次和游标保存在本机，网络恢复后继续。"
          />
          <PairingPoint
            icon={Cloud}
            title="仅主动连接"
            text="LinkAgent 不开放本机端口，只向 Link 平台发起连接。"
          />
        </div>
      </section>
      <form className="pairing-form" onSubmit={submit}>
        <div>
          <span className="step">首次设置</span>
          <h1>连接 Link 平台</h1>
          <p>在 Link 的“设置 - LinkAgent”中生成一次性配对码。</p>
        </div>
        <label>
          平台地址
          <input
            value={platformUrl}
            onChange={(event) => setPlatformUrl(event.target.value)}
            placeholder="https://link.example.com"
          />
        </label>
        <label>
          设备名称
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="我的 Mac"
          />
        </label>
        <label>
          配对码
          <input
            value={pairingCode}
            onChange={(event) => setPairingCode(event.target.value)}
            placeholder="输入一次性配对码"
            autoComplete="one-time-code"
            spellCheck={false}
          />
        </label>
        {formError && (
          <div className="form-error">
            <CircleAlert />
            {formError}
          </div>
        )}
        <button
          className="primary-button"
          type="submit"
          disabled={submitting || !pairingCode.trim()}
        >
          {submitting ? <LoaderCircle className="spin" /> : <Cable />}
          {submitting ? "正在连接" : "连接设备"}
        </button>
      </form>
    </main>
  );
}

function PairingPoint({
  icon: Icon,
  title,
  text,
}: {
  icon: typeof FolderKey;
  title: string;
  text: string;
}) {
  return (
    <div className="pairing-point">
      <Icon />
      <div>
        <strong>{title}</strong>
        <span>{text}</span>
      </div>
    </div>
  );
}

function DevicePage({ state, onOpenPlatform }: { state: AgentState; onOpenPlatform: () => void }) {
  return (
    <section className="page-stack">
      <div className="status-panel">
        <div className="status-icon">
          <Laptop />
        </div>
        <div className="status-copy">
          <div className="title-row">
            <h2>{state.displayName}</h2>
            <StatusBadge status={state.status} />
          </div>
          <p>这台设备通过 LinkAgent 安全运行本地连接器。</p>
        </div>
        <button className="secondary-button" onClick={onOpenPlatform}>
          <ExternalLink />
          打开 Link
        </button>
      </div>
      <div className="detail-list">
        <DetailRow label="平台地址" value={state.platformUrl} />
        <DetailRow label="最近心跳" value={formatDate(state.lastSeenAt)} />
        <DetailRow label="客户端版本" value={`LinkAgent ${state.version}`} />
        <DetailRow label="设备标识" value={state.agentId} technical />
      </div>
    </section>
  );
}

function ConnectorsPage({
  state,
  working,
  onAuthorize,
  onSync,
}: {
  state: AgentState;
  working: boolean;
  onAuthorize: () => void;
  onSync: () => void;
}) {
  return (
    <section className="page-stack">
      <div className="section-copy">
        <h2>本机连接器</h2>
        <p>连接器只读取你明确授权的数据范围。</p>
      </div>
      <article className="connector-card">
        <div className="connector-heading">
          <div className="connector-icon">
            <Terminal />
          </div>
          <div>
            <h3>Codex</h3>
            <p>输入、输出、CLI、工具和技能线索</p>
          </div>
          <StatusBadge
            status={
              !state.codexAvailable
                ? "unavailable"
                : state.codexAuthorized
                  ? "ready"
                  : "authorization_required"
            }
          />
        </div>
        <div className="connector-scope">
          <span>读取范围</span>
          <strong>{state.codexPath || "~/.codex"}</strong>
          <small>只读，不修改 Codex 本地文件</small>
        </div>
        <div className="connector-actions">
          {!state.codexAuthorized ? (
            <button
              className="primary-button compact"
              disabled={!state.codexAvailable || working}
              onClick={onAuthorize}
            >
              <FolderKey />
              确认只读授权
            </button>
          ) : (
            <button
              className="primary-button compact"
              disabled={working || state.syncing}
              onClick={onSync}
            >
              {working || state.syncing ? <LoaderCircle className="spin" /> : <Play />}
              {working || state.syncing ? "正在同步" : "立即同步"}
            </button>
          )}
          {state.lastSync && (
            <span className="last-run">
              上次同步 {formatDate(state.lastSync.completedAt)} · 上传{" "}
              {state.lastSync.uploaded.toLocaleString()} 条
            </span>
          )}
        </div>
      </article>
      <div className="future-note">
        <Cable />
        <div>
          <strong>下一批连接器</strong>
          <span>飞书和本地文件将在 Codex 客户端同步稳定后接入。</span>
        </div>
      </div>
    </section>
  );
}

function SyncPage({ state, logs }: { state: AgentState; logs: string[] }) {
  return (
    <section className="page-stack">
      <div className="section-copy">
        <h2>同步记录</h2>
        <p>查看最近任务结果和本机运行事件。</p>
      </div>
      {state.lastSync ? (
        <div className="sync-summary">
          <div className="summary-title">
            <CheckCircle2 />
            <div>
              <h3>Codex 同步完成</h3>
              <span>{formatDate(state.lastSync.completedAt)}</span>
            </div>
          </div>
          <div className="summary-metrics">
            <Metric label="本次读取" value={state.lastSync.selected} />
            <Metric label="已上传" value={state.lastSync.uploaded} />
            <Metric label="新增" value={state.lastSync.inserted} />
            <Metric label="更新" value={state.lastSync.updated} />
          </div>
        </div>
      ) : (
        <div className="empty-panel">
          <FileClock />
          <h3>还没有同步记录</h3>
          <p>完成 Codex 授权并发起第一次同步后，结果会显示在这里。</p>
        </div>
      )}
      <details className="log-panel">
        <summary>
          本地诊断日志 <ChevronRight />
        </summary>
        <div className="log-lines">
          {logs.length ? (
            logs.map((line, index) => (
              <code key={`${index}-${line.slice(0, 12)}`}>{formatLog(line)}</code>
            ))
          ) : (
            <span>暂无日志</span>
          )}
        </div>
      </details>
    </section>
  );
}

function SettingsPage({
  state,
  autostart,
  onAutostart,
  onUnpair,
}: {
  state: AgentState;
  autostart: boolean;
  onAutostart: (enabled: boolean) => void;
  onUnpair: () => void;
}) {
  return (
    <section className="page-stack">
      <div className="setting-row">
        <div>
          <strong>登录后自动启动</strong>
          <span>登录这台 Mac 后自动运行 LinkAgent。</span>
        </div>
        <button
          className={autostart ? "toggle on" : "toggle"}
          role="switch"
          aria-checked={autostart}
          onClick={() => onAutostart(!autostart)}
        >
          <span />
        </button>
      </div>
      <div className="setting-row">
        <div>
          <strong>后台运行</strong>
          <span>关闭窗口后继续保持心跳和同步队列。</span>
        </div>
        <StatusBadge status="enabled" />
      </div>
      <div className="setting-row">
        <div>
          <strong>客户端更新</strong>
          <span>当前版本 {state.version}，第一期通过下载安装包更新。</span>
        </div>
        <button className="secondary-button" disabled>
          已是当前版本
        </button>
      </div>
      <div className="danger-zone">
        <div>
          <strong>解除设备配对</strong>
          <span>删除本机设备凭据，游标和队列暂时保留。</span>
        </div>
        <button className="danger-button" onClick={onUnpair}>
          <LogOut />
          解除配对
        </button>
      </div>
    </section>
  );
}

function DetailRow({
  label,
  value,
  technical = false,
}: {
  label: string;
  value: string;
  technical?: boolean;
}) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      <strong className={technical ? "technical" : ""}>{value || "暂无"}</strong>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}

function StatusDot({ status }: { status: AgentState["status"] }) {
  return <span className={`status-dot ${status}`} />;
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${status}`}>{connectorStatusLabel(status)}</span>;
}

function statusLabel(status: AgentState["status"]) {
  return { online: "已连接", offline: "平台离线", unpaired: "未配对" }[status];
}

function connectorStatusLabel(status: string) {
  return (
    (
      {
        online: "已连接",
        offline: "离线",
        ready: "已就绪",
        authorization_required: "待授权",
        unavailable: "未找到",
        enabled: "已启用",
      } as Record<string, string>
    )[status] || status
  );
}

function formatDate(value: string) {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatLog(line: string) {
  try {
    const value = JSON.parse(line) as { at?: string; event?: string };
    return `${formatDate(value.at || "")}  ${logEventLabel(value.event || "event")}`;
  } catch {
    return line;
  }
}

function logEventLabel(event: string) {
  return (
    (
      {
        paired: "设备配对成功",
        codex_authorized: "Codex 已授权",
        codex_sync_started: "Codex 开始同步",
        codex_sync_finished: "Codex 同步完成",
        codex_sync_failed: "Codex 同步失败",
        heartbeat_failed: "平台心跳失败",
        unpaired: "设备已解除配对",
      } as Record<string, string>
    )[event] || event
  );
}

function toMessage(error: unknown) {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return "操作失败，请稍后重试";
}

export default App;
