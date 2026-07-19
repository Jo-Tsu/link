import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ArrowLeft, DatabaseZap, RefreshCw, Terminal } from "lucide-react";

export const Route = createFileRoute("/codex")({
  head: () => ({ meta: [{ title: "Codex 连接器 · link" }] }),
  component: CodexConnectorPage,
});

type Connector = {
  threadCount: number;
  total: number;
  errors: number;
  latestSyncedAt: string;
  rawTypes: Array<{ type: string; count: number }>;
  originLabel: string;
  readScope: string;
  storageTable: string;
};
type RawRecord = {
  id: string;
  rawType: string;
  rawLabel: string;
  summary: string;
  rawText: string;
  occurredAt: string;
  threadTitle: string;
  projectPath: string;
  sourceUri: string;
  sensitivityLevel: string;
  noiseLevel: string;
};
type DeviceAgent = { id: string; displayName: string; status: string; lastSeenAt: string };

function CodexConnectorPage() {
  const [connector, setConnector] = useState<Connector | undefined>();
  const [agents, setAgents] = useState<DeviceAgent[]>([]);
  const [records, setRecords] = useState<RawRecord[]>([]);
  const [total, setTotal] = useState(0);
  const initialContainer =
    typeof window === "undefined"
      ? ""
      : new URLSearchParams(window.location.search).get("container") || "";
  const [query, setQuery] = useState("");
  const [containerId, setContainerId] = useState(initialContainer);
  const [rawType, setRawType] = useState("all");
  const [offset, setOffset] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");
  const limit = 40;

  const load = useCallback(
    async (nextOffset = 0, nextQuery = "", nextType = "all", nextContainer = "") => {
      const [connectorResponse, recordResponse, agentResponse] = await Promise.all([
        fetch("/api/connectors/status"),
        fetch(
          `/api/sensory-records?source=codex&rawType=${encodeURIComponent(nextType)}&containerIds=${encodeURIComponent(nextContainer)}&q=${encodeURIComponent(nextQuery)}&limit=${limit}&offset=${nextOffset}`,
        ),
        fetch("/api/agents"),
      ]);
      const connectorResult = (await connectorResponse.json()) as {
        connectors?: Array<Connector & { source: string }>;
      };
      const recordResult = (await recordResponse.json()) as {
        records?: RawRecord[];
        total?: number;
      };
      const agentResult = (await agentResponse.json()) as { agents?: DeviceAgent[] };
      setConnector(connectorResult.connectors?.find((item) => item.source === "codex"));
      setRecords(recordResult.records ?? []);
      setTotal(recordResult.total ?? 0);
      setAgents(agentResult.agents ?? []);
    },
    [],
  );

  useEffect(() => {
    void load(0, "", "all", initialContainer);
  }, [initialContainer, load]);

  const applyFilters = () => {
    setOffset(0);
    void load(0, query, rawType, containerId);
  };
  const sync = async () => {
    const agent = agents.find((item) => item.status === "online") || agents[0];
    if (!agent) {
      setMessage("尚未配对 LinkAgent。请先在设置中生成配对码并连接设备。");
      return;
    }
    setSyncing(true);
    setMessage("正在向 LinkAgent 下发 Codex 同步指令。");
    try {
      const response = await fetch("/api/agents/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agentId: agent.id,
          type: "sync_connector",
          payload: { connectorId: "codex_local" },
        }),
      });
      const result = (await response.json()) as {
        ok?: boolean;
        error?: string;
      };
      if (!response.ok || !result.ok) throw new Error(result.error || "同步失败");
      setMessage(
        agent.status === "online"
          ? "同步指令已下发，Agent 正在或将在下一次心跳时执行。"
          : "Agent 当前离线，同步指令会在其恢复在线后执行。",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-5 p-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 mb-2">
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            基础数据
          </Link>
        </Button>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Terminal className="h-5 w-5 text-primary" />
          Codex 本地历史
        </h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
          由 LinkAgent 只读读取本机 Codex 历史，写入 sensory_records 原始池。
        </p>
      </div>
      <Card className="border-border/60">
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <DatabaseZap className="h-4 w-4 text-primary" />
              连接器状态
            </CardTitle>
            <p className="mt-2 text-xs text-muted-foreground">
              {connector?.readScope || "正在读取连接器配置"}
            </p>
          </div>
          <Button size="sm" onClick={() => void sync()} disabled={syncing}>
            <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "下发中" : "请求同步"}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <Metric label="来源容器" value={connector?.threadCount ?? 0} />
            <Metric label="原始记录" value={connector?.total ?? 0} />
            <Metric label="同步错误" value={connector?.errors ?? 0} />
            <Metric label="最近同步" value={formatDate(connector?.latestSyncedAt || "")} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {connector?.rawTypes.map((item) => (
              <Badge key={item.type} variant="outline">
                {rawTypeLabel(item.type)} {item.count}
              </Badge>
            ))}
          </div>
          <div className="text-xs text-muted-foreground">
            {agents.length
              ? `LinkAgent：${agents.find((item) => item.status === "online")?.displayName || agents[0]?.displayName}（${agents.find((item) => item.status === "online") ? "在线" : "离线"}）`
              : "未配对 LinkAgent，请前往设置完成配对。"}
          </div>
          {message && (
            <div className="rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
              {message}
            </div>
          )}
        </CardContent>
      </Card>
      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">原始数据项</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              保留连接器来源、线程、项目路径、时间与原文摘要；当前不做数据处理。
            </p>
          </div>
          <Badge variant="outline">{total.toLocaleString()} 条</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={rawType}
            onChange={(event) => setRawType(event.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="all">全部类型</option>
            <option value="user_input">用户输入</option>
            <option value="codex_output">Codex 输出</option>
            <option value="cli">CLI</option>
            <option value="tool">工具</option>
            <option value="skill">技能</option>
          </select>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && applyFilters()}
            placeholder="搜索标题、项目路径或原始内容"
            className="max-w-md"
          />
          {containerId && (
            <Button
              variant="outline"
              onClick={() => {
                setContainerId("");
                setOffset(0);
                void load(0, query, rawType, "");
              }}
            >
              清除来源筛选
            </Button>
          )}
          <Button variant="outline" onClick={applyFilters}>
            搜索
          </Button>
        </div>
        <div className="space-y-2">
          {records.map((record) => (
            <Card key={record.id} className="border-border/60">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{rawTypeLabel(record.rawType)}</Badge>
                      {record.sensitivityLevel === "sensitive" && (
                        <Badge variant="outline">敏感</Badge>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {formatDate(record.occurredAt)}
                      </span>
                    </div>
                    <div className="mt-2 text-sm font-medium">
                      {record.threadTitle || "未命名来源"}
                    </div>
                    <div className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
                      {record.summary || record.rawText}
                    </div>
                    {record.projectPath && (
                      <div className="mt-2 text-[11px] text-muted-foreground">
                        {record.projectPath}
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
        {records.length === 0 && (
          <div className="rounded-md border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
            没有匹配的原始数据。
          </div>
        )}
        <div className="flex justify-between">
          <Button
            variant="outline"
            disabled={offset === 0}
            onClick={() => {
              const next = Math.max(0, offset - limit);
              setOffset(next);
              void load(next);
            }}
          >
            上一页
          </Button>
          <span className="text-sm text-muted-foreground">
            {offset + 1}-{Math.min(offset + records.length, total)} / {total}
          </span>
          <Button
            variant="outline"
            disabled={offset + limit >= total}
            onClick={() => {
              const next = offset + limit;
              setOffset(next);
              void load(next);
            }}
          >
            下一页
          </Button>
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-border/50 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}
function formatDate(value: string) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "暂无";
}
function rawTypeLabel(type: string) {
  return (
    { user_input: "用户输入", codex_output: "Codex 输出", cli: "CLI", tool: "工具", skill: "技能" }[
      type
    ] || type
  );
}
